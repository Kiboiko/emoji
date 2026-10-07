"""
Текст инструкции не достаётся тому, кто за неё не заплатил.

У товара-инструкции продаётся сам текст из content_data. Каталог его прятал,
но текст уходил наружу двумя обходными путями:

- снапшот заказа пишется при оформлении, до оплаты, и GET /api/orders/{id}
  отдавал его целиком: достаточно было оформить заказ и не платить;
- создание и правка товара в админке рассылались по WebSocket всем
  подключённым вместе с content_data.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from models.cart import CartItem
from models.category import Category
from models.order import CurrencyType, OrderItem
from models.product import Product
from routes import orders as order_routes
from routes import products as product_routes
from schemas.order import OrderCreate
from utils.websockets import manager

pytestmark = pytest.mark.asyncio

SECRET = "Шаг 1: то, за что платят"


@pytest.fixture
async def category(db):
    row = Category(id=uuid.uuid4(), name_ru="Тест", name_en="Test")
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def instruction(db, category):
    product = Product(
        id=uuid.uuid4(),
        name_ru="Инструкция", name_en="Guide",
        description_ru="Описание", description_en="Description",
        price_usdt=Decimal("5.00"), image_url="/uploads/x.jpg",
        category_id=category.id, stock=None, type="instruction",
        content_data={"instruction": SECRET},
    )
    db.add(product)
    await db.flush()
    return product


@pytest.fixture
def broadcasts(monkeypatch):
    """Всё, что ушло бы в рассылку по WebSocket."""
    sent = []

    async def capture(message):
        sent.append(message)

    monkeypatch.setattr(manager, "broadcast", capture)
    return sent


def _stub_payment(monkeypatch):
    """Счёт выставляется без обращения к сети — как в test_payment_service."""
    from config import settings as cfg
    from services import ton_service

    monkeypatch.setattr(cfg, "TON_RECEIVING_ADDRESS", "0QPlatformWallet")

    async def fake_rate(_db):
        return Decimal("3.000000000")

    monkeypatch.setattr(ton_service, "get_rate", fake_rate)


async def _unpaid_order(db, buyer, product) -> str:
    """Корзина → заказ, как на витрине. Оплаты нет."""
    db.add(CartItem(id=uuid.uuid4(), user_id=buyer.id, product_id=product.id, quantity=1))
    await db.flush()

    created = await order_routes.create_order(
        OrderCreate(currency=CurrencyType.TON, accept_terms=True), user=buyer, db=db,
    )
    return created["order_id"]


def _admin_form(**fields) -> dict:
    """
    Все поля формы правки товара.

    Эндпоинт вызывается напрямую, мимо FastAPI: неуказанное поле получило бы
    значением сам объект Form(None), а не None, и правка записала бы его в товар.
    """
    form = dict.fromkeys((
        "name_ru", "name_en", "description_ru", "description_en", "price_usdt",
        "category_id", "is_top", "is_active", "type", "image", "digital_file",
        "instruction_text",
    ))
    form.update(fields)
    return form


class TestUnpaidOrder:

    async def test_order_does_not_reveal_instruction(
        self, db, user_factory, instruction, monkeypatch,
    ):
        """Ровно тот путь, которым текст уходил бесплатно: корзина, заказ, запрос заказа."""
        _stub_payment(monkeypatch)
        buyer = await user_factory(username="freeloader")
        order_id = await _unpaid_order(db, buyer, instruction)

        order = await order_routes.get_order(order_id, user=buyer, db=db)

        snapshot = order.items[0].product_snapshot
        assert "content_data" not in snapshot
        assert SECRET not in str(order.model_dump())
        # Остальное витрине нужно: по этим полям рисуется заказ
        assert snapshot["name_ru"] == "Инструкция"
        assert snapshot["type"] == "instruction"

    async def test_instruction_stays_in_db_for_delivery(
        self, db, user_factory, instruction, monkeypatch,
    ):
        """
        Прячем только в ответе, а не в базе.

        После оплаты complete_order берёт текст из снапшота строки заказа и
        отправляет его в Telegram. Если ответ API вырезал бы поле из самой
        строки, оплативший остался бы без покупки.
        """
        _stub_payment(monkeypatch)
        buyer = await user_factory(username="honest_buyer")
        order_id = await _unpaid_order(db, buyer, instruction)

        await order_routes.get_order(order_id, user=buyer, db=db)

        item = (
            await db.execute(select(OrderItem).where(OrderItem.order_id == uuid.UUID(order_id)))
        ).scalar_one()
        assert item.product_snapshot["content_data"] == {"instruction": SECRET}


class TestDeliveryPage:
    """Купленное видно на странице покупки — но только после оплаты."""

    async def _order_and_item(self, db, buyer, product, monkeypatch):
        _stub_payment(monkeypatch)
        order_id = await _unpaid_order(db, buyer, product)
        item = (
            await db.execute(select(OrderItem).where(OrderItem.order_id == uuid.UUID(order_id)))
        ).scalar_one()
        return uuid.UUID(order_id), item.id

    async def test_unpaid_order_shows_nothing(self, db, user_factory, instruction, monkeypatch):
        from fastapi import HTTPException

        buyer = await user_factory(username="delivery_freeloader")
        order_id, item_id = await self._order_and_item(db, buyer, instruction, monkeypatch)

        with pytest.raises(HTTPException) as exc:
            await order_routes.item_delivery(order_id, item_id, user=buyer, db=db)
        assert exc.value.status_code == 403

    async def test_paid_order_shows_the_instruction(self, db, user_factory, instruction, monkeypatch):
        from models.order import Order, OrderStatus

        buyer = await user_factory(username="delivery_buyer")
        order_id, item_id = await self._order_and_item(db, buyer, instruction, monkeypatch)
        (await db.get(Order, order_id)).status = OrderStatus.COMPLETED
        await db.flush()

        result = await order_routes.item_delivery(order_id, item_id, user=buyer, db=db)

        assert result["kind"] == "instruction"
        assert result["instruction"] == SECRET

    async def test_someone_elses_order_is_not_found(self, db, user_factory, instruction, monkeypatch):
        from fastapi import HTTPException
        from models.order import Order, OrderStatus

        buyer = await user_factory(username="delivery_owner")
        stranger = await user_factory(username="delivery_stranger")
        order_id, item_id = await self._order_and_item(db, buyer, instruction, monkeypatch)
        (await db.get(Order, order_id)).status = OrderStatus.COMPLETED
        await db.flush()

        with pytest.raises(HTTPException) as exc:
            await order_routes.item_delivery(order_id, item_id, user=stranger, db=db)
        assert exc.value.status_code == 404


class TestBroadcast:

    async def test_edit_does_not_broadcast_instruction(
        self, db, user_factory, instruction, broadcasts,
    ):
        """
        Любая правка — хоть пометка «топ» — рассылалась всем с текстом внутри.
        """
        admin = await user_factory(username="catalog_admin", is_admin=True)

        returned = await product_routes.update_product(
            str(instruction.id), **_admin_form(is_top=True), admin=admin, db=db,
        )

        assert len(broadcasts) == 1
        data = broadcasts[0]["data"]
        assert "content_data" not in data
        assert SECRET not in str(broadcasts)
        # По этим полям витрина обновляет карточку на месте
        assert data["id"] == str(instruction.id)
        assert data["name_ru"] == "Инструкция"
        assert data["is_top"] is True
        # Админке, наоборот, текст нужен: из ответа она заполняет форму правки
        assert returned.content_data == {"instruction": SECRET}

    async def test_new_instruction_is_not_broadcast(
        self, db, user_factory, category, broadcasts,
    ):
        admin = await user_factory(username="catalog_admin_2", is_admin=True)

        returned = await product_routes.create_product(
            name_ru="Новая инструкция", name_en="New guide",
            description_ru="Описание", description_en="Description",
            price_usdt=5.0, category_id=str(category.id), type="instruction",
            is_top=False, min_quantity=1, image=None, digital_file=None,
            instruction_text=SECRET, admin=admin, db=db,
        )

        assert broadcasts[0]["type"] == "product_created"
        assert "content_data" not in broadcasts[0]["data"]
        assert SECRET not in str(broadcasts)
        assert returned.content_data == {"instruction": SECRET}
