"""
Отмена заказа покупателем и лимит количества в корзине.

Обе вещи про одно: товар пользователя существует в единственном экземпляре.
Пока он лежит в чужом неоплаченном заказе, его не видит никто, а продавец
ничего не может сделать. И положить в корзину две штуки того, что существует
в одном, нельзя даже в теории.

Оба бага нашёл заказчик при живом прогоне в Mini App.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from models.category import Category
from models.order import CurrencyType, Order, OrderItem, OrderStatus
from models.payment import Payment, PaymentStatus
from models.product import Product
from models.cart import CartItem
from routes import cart as cart_routes
from routes import orders as order_routes
from schemas.cart import CartItemCreate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def category(db):
    row = Category(id=uuid.uuid4(), name_ru="Тест", name_en="Test")
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def unique_item(db, category, user_factory):
    """Товар пользователя: ровно одна штука, больше одной не купить."""
    seller = await user_factory(username=f"seller_{uuid.uuid4().hex[:6]}")
    product = Product(
        id=uuid.uuid4(),
        name_ru="Единственная вещь", name_en="One of a kind",
        description_ru="Описание", description_en="Description",
        price_usdt=Decimal("7.50"), image_url="/uploads/x.jpg",
        category_id=category.id, stock=1, type="p2p",
        max_quantity=1, owner_user_id=seller.id, is_p2p=True, content_data={},
    )
    db.add(product)
    await db.flush()
    return product


async def _pending_order(db, buyer, product, *, quantity=1):
    """Заказ в ожидании оплаты, держащий товар в резерве."""
    order = Order(
        id=uuid.uuid4(), user_id=buyer.id, total_usdt=Decimal("7.50"),
        currency=CurrencyType.TON, status=OrderStatus.PENDING,
        created_at=datetime.utcnow(),
    )
    db.add(order)
    await db.flush()
    db.add(OrderItem(
        id=uuid.uuid4(), order_id=order.id, product_id=product.id,
        product_snapshot={"name_ru": product.name_ru, "type": "p2p", "is_p2p": True},
        quantity=quantity, price_usdt=Decimal("7.50"),
    ))
    product.stock -= quantity          # как при оформлении заказа
    await db.flush()
    await db.refresh(order, ["items"])
    return order


# ---------------------------------------------------------------------------
# Корзина
# ---------------------------------------------------------------------------

class TestCartQuantityLimit:

    async def test_adding_twice_does_not_exceed_limit(self, db, user_factory, unique_item):
        """
        Два раза по одной штуке — не две штуки.

        Проверка лимита смотрела только на приходящую добавку, а количество
        при этом прибавлялось к тому, что уже лежит. «Добавить в корзину»
        дважды обходило max_quantity, и в корзине оказывались две единицы
        товара, существующего в одном экземпляре.
        """
        buyer = await user_factory(username="cart_buyer")
        payload = CartItemCreate(product_id=unique_item.id, quantity=1)

        await cart_routes.add_to_cart(item_data=payload, user=buyer, db=db)

        with pytest.raises(HTTPException) as exc:
            await cart_routes.add_to_cart(item_data=payload, user=buyer, db=db)

        assert exc.value.status_code == 400
        # Текст по-русски и про суть: товар уже в корзине покупателя,
        # а не «превышено максимальное количество»
        assert "уже в корзине" in exc.value.detail

        rows = (await db.execute(
            CartItem.__table__.select().where(CartItem.user_id == buyer.id)
        )).all()
        assert len(rows) == 1
        assert rows[0].quantity == 1

    async def test_cannot_exceed_stock_by_adding_up(self, db, user_factory, category):
        """Сумма добавлений не может превысить остаток на складе."""
        product = Product(
            id=uuid.uuid4(),
            name_ru="Две штуки", name_en="Two left",
            description_ru="Описание", description_en="Description",
            price_usdt=Decimal("5.00"), image_url="/uploads/x.jpg",
            category_id=category.id, stock=2, type="digital", content_data={},
        )
        db.add(product)
        await db.flush()

        buyer = await user_factory(username="stock_buyer")
        payload = CartItemCreate(product_id=product.id, quantity=2)

        await cart_routes.add_to_cart(item_data=payload, user=buyer, db=db)

        with pytest.raises(HTTPException) as exc:
            await cart_routes.add_to_cart(item_data=payload, user=buyer, db=db)

        assert exc.value.status_code == 400
        assert "2" in exc.value.detail


# ---------------------------------------------------------------------------
# Отмена заказа
# ---------------------------------------------------------------------------

class TestCancelOrder:

    async def test_cancel_returns_item_to_sale(self, db, user_factory, unique_item):
        """
        Отмена возвращает вещь на витрину немедленно.

        До появления этой кнопки товар ждал прогона планировщика — до часа,
        а при неверно выставленном сроке жизни счёта и до половины суток.
        """
        buyer = await user_factory(username="cancel_buyer")
        order = await _pending_order(db, buyer, unique_item)
        assert unique_item.stock == 0

        result = await order_routes.cancel_order(str(order.id), user=buyer, db=db)

        assert result["status"] == OrderStatus.CANCELLED.value
        await db.refresh(unique_item)
        assert unique_item.stock == 1

    async def test_cannot_cancel_someone_elses_order(self, db, user_factory, unique_item):
        buyer = await user_factory(username="owner_buyer")
        stranger = await user_factory(username="stranger")
        order = await _pending_order(db, buyer, unique_item)

        with pytest.raises(HTTPException) as exc:
            await order_routes.cancel_order(str(order.id), user=stranger, db=db)

        assert exc.value.status_code == 403
        await db.refresh(unique_item)
        assert unique_item.stock == 0      # чужой товар не освобождён

    async def test_paid_order_cannot_be_cancelled(self, db, user_factory, unique_item):
        """
        Оплаченный заказ кнопкой не отменяется.

        Деньги уже пришли; возврат — это разбор через поддержку, а не
        самообслуживание, иначе можно оплатить, отменить и остаться с товаром.
        """
        buyer = await user_factory(username="paid_buyer")
        order = await _pending_order(db, buyer, unique_item)
        order.status = OrderStatus.PAID
        await db.flush()

        with pytest.raises(HTTPException) as exc:
            await order_routes.cancel_order(str(order.id), user=buyer, db=db)

        assert exc.value.status_code == 400

    async def test_confirmed_payment_blocks_cancellation(self, db, user_factory, unique_item):
        """
        Гонка: платёж подтвердился, пока человек жал «отменить».

        Статус заказа ещё PENDING — его меняет поллер, — но деньги уже
        зачтены. Отменять в этот момент нельзя, иначе товар вернётся в
        продажу при оплаченном заказе.
        """
        buyer = await user_factory(username="race_buyer")
        order = await _pending_order(db, buyer, unique_item)
        db.add(Payment(
            id=uuid.uuid4(), order_id=order.id, user_id=buyer.id,
            amount_nano=1_000_000_000, usd_amount=Decimal("7.50"),
            rate_usd_per_ton=Decimal("3.000000000"),
            rate_locked_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            destination_address="0QPlatform",
            payment_comment=f"MP-{uuid.uuid4().hex[:12].upper()}",
            status=PaymentStatus.CONFIRMED,
        ))
        await db.flush()

        with pytest.raises(HTTPException) as exc:
            await order_routes.cancel_order(str(order.id), user=buyer, db=db)

        assert exc.value.status_code == 400
        await db.refresh(unique_item)
        assert unique_item.stock == 0

    async def test_second_cancel_is_harmless(self, db, user_factory, unique_item):
        """
        Повторное нажатие не возвращает сток дважды.

        Кнопка могла не успеть исчезнуть, и второй тап не должен
        превращать одну вещь в две.
        """
        buyer = await user_factory(username="double_buyer")
        order = await _pending_order(db, buyer, unique_item)

        await order_routes.cancel_order(str(order.id), user=buyer, db=db)
        await order_routes.cancel_order(str(order.id), user=buyer, db=db)

        await db.refresh(unique_item)
        assert unique_item.stock == 1


class TestQuantityCeiling:
    """
    Потолок количества и его соблюдение при ПРАВКЕ, а не только при добавлении.

    Заказчик нажимал «плюс» у штучного товара: количество и сумма на мгновение
    менялись, и только потом приходил отказ. Витрина рисовала новое значение,
    не зная предела, — а предел ей никто не сообщал.
    """

    async def test_cart_reports_the_ceiling(self, db, user_factory, unique_item):
        buyer = await user_factory(username="ceiling_buyer")
        db.add(CartItem(
            id=uuid.uuid4(), user_id=buyer.id,
            product_id=unique_item.id, quantity=1,
        ))
        await db.flush()

        cart = await cart_routes.get_cart(user=buyer, db=db)

        assert cart.items[0]["max_quantity"] == 1

    async def test_ceiling_is_the_smaller_of_the_two_limits(
        self, db, user_factory, category,
    ):
        """Разрешено взять 5, а на складе 2 — потолок равен двум."""
        product = Product(
            id=uuid.uuid4(),
            name_ru="Ключи", name_en="Keys",
            description_ru="Описание", description_en="Description",
            price_usdt=Decimal("3.00"), image_url="/uploads/x.jpg",
            category_id=category.id, stock=2, type="digital",
            max_quantity=5, content_data={},
        )
        db.add(product)
        buyer = await user_factory(username="ceiling_buyer2")
        db.add(CartItem(
            id=uuid.uuid4(), user_id=buyer.id, product_id=product.id, quantity=1,
        ))
        await db.flush()

        cart = await cart_routes.get_cart(user=buyer, db=db)

        assert cart.items[0]["max_quantity"] == 2

    async def test_no_limits_means_no_ceiling(self, db, user_factory, category):
        """Услуга без ограничений не должна гасить «плюс»."""
        product = Product(
            id=uuid.uuid4(),
            name_ru="Услуга", name_en="Service",
            description_ru="Описание", description_en="Description",
            price_usdt=Decimal("1.00"), image_url="/uploads/x.jpg",
            category_id=category.id, stock=None, type="service",
            max_quantity=None, content_data={},
        )
        db.add(product)
        buyer = await user_factory(username="ceiling_buyer3")
        db.add(CartItem(
            id=uuid.uuid4(), user_id=buyer.id, product_id=product.id, quantity=1,
        ))
        await db.flush()

        cart = await cart_routes.get_cart(user=buyer, db=db)

        assert cart.items[0]["max_quantity"] is None

    async def test_update_cannot_exceed_stock(self, db, user_factory, category):
        """
        Смежная дыра: сток проверялся только при добавлении в корзину.

        Можно было положить последнюю штуку, а потом «плюсом» набрать больше,
        чем существует, — и упереться в это уже на оплате.
        """
        product = Product(
            id=uuid.uuid4(),
            name_ru="Остаток", name_en="Last ones",
            description_ru="Описание", description_en="Description",
            price_usdt=Decimal("4.00"), image_url="/uploads/x.jpg",
            category_id=category.id, stock=2, type="digital",
            max_quantity=None, content_data={},
        )
        db.add(product)
        buyer = await user_factory(username="stock_buyer")
        item = CartItem(
            id=uuid.uuid4(), user_id=buyer.id, product_id=product.id, quantity=2,
        )
        db.add(item)
        await db.flush()

        from schemas.cart import CartItemUpdate

        with pytest.raises(HTTPException) as exc:
            await cart_routes.update_cart_item(
                str(item.id), CartItemUpdate(quantity=3), user=buyer, db=db,
            )
        assert exc.value.status_code == 400

        await db.refresh(item)
        assert item.quantity == 2, "количество изменилось вопреки отказу"
