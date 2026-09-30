"""
Повторное «Оплатить» и честный остаток товара продавца.

Кошелёк в Telegram иногда открывается не до конца: человек закрывает его и
жмёт «Оплатить» ещё раз. Раньше каждое нажатие создавало новый заказ, а
прошлый держал товар полчаса — и повторная попытка упиралась в собственную
бронь покупателя: «Товар уже продан». Вещь при этом пропадала из каталога,
а продавец видел у себя «В продаже».
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.cart import CartItem
from models.category import Category
from models.order import CurrencyType, Order, OrderItem, OrderStatus
from models.p2p import Deal, DealStatus, ListingStatus, ProductListing, SellerProfile
from models.payment import Payment, PaymentStatus
from models.product import Product
from routes import orders as order_routes
from routes import p2p as p2p_routes
from schemas.order import OrderCreate
from services import scheduler as sched

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def stub_payment(monkeypatch):
    """Счёт выставляется без обращения к сети — как в test_payment_service."""
    from config import settings as cfg
    from services import ton_service

    monkeypatch.setattr(cfg, "TON_RECEIVING_ADDRESS", "0QPlatformWallet")

    async def fake_rate(_db):
        return Decimal("3.000000000")

    monkeypatch.setattr(ton_service, "get_rate", fake_rate)


@pytest.fixture
async def category(db):
    row = Category(id=uuid.uuid4(), name_ru="Вещи", name_en="Things")
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def seller(db, user_factory):
    user = await user_factory(username=f"retry_seller_{uuid.uuid4().hex[:6]}")
    profile = SellerProfile(
        id=uuid.uuid4(), user_id=user.id,
        display_name=f"Магазин {uuid.uuid4().hex[:6]}",
        payout_wallet="UQSellerWallet0000",
    )
    db.add(profile)
    await db.flush()
    return user


async def _listed(db, category, seller, *, quantity=1, name="Клавиатура") -> tuple[Product, ProductListing]:
    """Одобренная заявка и её товар в каталоге — как после модерации."""
    profile = (
        await db.execute(select(SellerProfile).where(SellerProfile.user_id == seller.id))
    ).scalars().one()
    product = Product(
        id=uuid.uuid4(),
        name_ru=name, name_en=name,
        description_ru="описание", description_en="description",
        price_usdt=Decimal("10.00"), image_url="/uploads/listings/a.jpg",
        category_id=category.id, type="p2p",
        min_quantity=1, max_quantity=quantity, stock=quantity,
        owner_user_id=seller.id, is_p2p=True, content_data={},
    )
    db.add(product)
    await db.flush()
    listing = ProductListing(
        id=uuid.uuid4(), seller_id=profile.id, product_id=product.id,
        category_id=category.id, name=name, description="описание",
        price_usd=Decimal("10.00"), quantity=quantity, status=ListingStatus.APPROVED,
    )
    db.add(listing)
    await db.flush()
    return product, listing


async def _checkout(db, buyer, *products) -> dict:
    """Корзина → «Оплатить», как на витрине."""
    for existing in (
        await db.execute(select(CartItem).where(CartItem.user_id == buyer.id))
    ).scalars().all():
        await db.delete(existing)
    for product in products:
        db.add(CartItem(id=uuid.uuid4(), user_id=buyer.id, product_id=product.id, quantity=1))
    await db.flush()

    return await order_routes.create_order(
        OrderCreate(currency=CurrencyType.TON, accept_terms=True), user=buyer, db=db,
    )


async def _sold(db, product, seller, user_factory, *, quantity=1) -> None:
    """Сделка по оплаченному заказу — товар ушёл покупателю."""
    buyer = await user_factory(username=f"retry_paid_{uuid.uuid4().hex[:6]}")
    order = Order(
        id=uuid.uuid4(), user_id=buyer.id, total_usdt=Decimal("10.00"),
        currency=CurrencyType.TON, status=OrderStatus.PAID,
    )
    db.add(order)
    await db.flush()
    item = OrderItem(
        id=uuid.uuid4(), order_id=order.id, product_id=product.id, quantity=quantity,
        price_usdt=Decimal("10.00"),
        product_snapshot={"name_ru": product.name_ru, "type": "p2p", "is_p2p": True},
    )
    db.add(item)
    await db.flush()
    db.add(Deal(
        id=uuid.uuid4(), order_id=order.id, order_item_id=item.id,
        buyer_id=buyer.id, seller_id=seller.id, product_id=product.id,
        product_name=product.name_ru, status=DealStatus.CHAT_OPENED,
    ))
    await db.flush()


class TestRetry:

    async def test_second_pay_returns_the_same_order(self, db, user_factory, category, seller):
        """
        Главный случай из жалобы: кошелёк закрыли, «Оплатить» нажали снова.
        Тот же заказ и тот же перевод — вместо «Товар уже продан».
        """
        product, _ = await _listed(db, category, seller)
        buyer = await user_factory(username="retry_buyer")

        first = await _checkout(db, buyer, product)
        second = await _checkout(db, buyer, product)

        assert second["order_id"] == first["order_id"]
        assert second["payment"]["comment"] == first["payment"]["comment"]

        await db.refresh(product)
        assert product.stock == 0          # одна бронь, а не две
        pending = (
            await db.execute(
                select(Order).where(Order.user_id == buyer.id, Order.status == OrderStatus.PENDING)
            )
        ).scalars().all()
        assert len(pending) == 1

    async def test_changed_cart_releases_the_previous_order(
        self, db, user_factory, category, seller,
    ):
        """Корзину поменяли — прежний заказ снимается и отпускает товар."""
        first_item, _ = await _listed(db, category, seller, name="Мышь")
        second_item, _ = await _listed(db, category, seller, name="Коврик")
        buyer = await user_factory(username="retry_switch")

        first = await _checkout(db, buyer, first_item)
        second = await _checkout(db, buyer, second_item)

        assert second["order_id"] != first["order_id"]
        old = await db.get(Order, uuid.UUID(first["order_id"]))
        await db.refresh(old)
        await db.refresh(first_item)
        assert old.status == OrderStatus.CANCELLED
        assert first_item.stock == 1

    async def test_payment_already_on_chain_is_not_duplicated(
        self, db, user_factory, category, seller,
    ):
        """
        Перевод по прошлому заказу уже виден в сети — новый заказ не создаём:
        иначе покупатель заплатил бы дважды.
        """
        product, _ = await _listed(db, category, seller)
        buyer = await user_factory(username="retry_seen")

        first = await _checkout(db, buyer, product)
        payment = (
            await db.execute(
                select(Payment).where(Payment.order_id == uuid.UUID(first["order_id"]))
            )
        ).scalars().one()
        payment.status = PaymentStatus.SEEN
        await db.flush()

        with pytest.raises(HTTPException) as exc:
            await _checkout(db, buyer, product)

        assert exc.value.status_code == 409
        assert "подтверждается" in exc.value.detail

    async def test_someone_elses_reservation_is_named_honestly(
        self, db, user_factory, category, seller,
    ):
        """Чужая бронь — не «уже продан»: товар ещё может вернуться."""
        product, _ = await _listed(db, category, seller)
        first = await user_factory(username="retry_first")
        second = await user_factory(username="retry_second")

        await _checkout(db, first, product)
        with pytest.raises(HTTPException) as exc:
            await _checkout(db, second, product)

        assert "другой покупатель" in exc.value.detail
        assert "уже продан" not in exc.value.detail

    async def test_really_sold_item_says_sold(self, db, user_factory, category, seller):
        product, _ = await _listed(db, category, seller)
        await _sold(db, product, seller, user_factory)
        product.stock = 0
        await db.flush()

        buyer = await user_factory(username="retry_late")
        with pytest.raises(HTTPException) as exc:
            await _checkout(db, buyer, product)

        assert "уже продан" in exc.value.detail


class TestHonestStock:

    async def test_quantity_edit_keeps_sold_units_out(
        self, db, user_factory, category, seller,
    ):
        """
        Продали одну из одной, продавец поставил количество 10 — в продаже
        девять, а не снова все десять.
        """
        product, listing = await _listed(db, category, seller)
        await _sold(db, product, seller, user_factory)
        product.stock = 0
        await db.flush()

        await p2p_routes.update_listing(
            listing.id, p2p_routes.ListingUpdate(quantity=10), user=seller, db=db,
        )

        await db.refresh(product)
        assert product.stock == 9

    async def test_quantity_below_sold_is_refused(self, db, user_factory, category, seller):
        product, listing = await _listed(db, category, seller, quantity=3)
        await _sold(db, product, seller, user_factory, quantity=2)

        with pytest.raises(HTTPException) as exc:
            await p2p_routes.update_listing(
                listing.id, p2p_routes.ListingUpdate(quantity=1), user=seller, db=db,
            )

        assert exc.value.status_code == 400
        assert "продано 2" in exc.value.detail

    async def test_expired_reservation_does_not_revive_withdrawn_item(
        self, db, user_factory, category, seller, monkeypatch,
    ):
        """
        Покупатель оформил заказ, продавец тем временем снял товар. Когда
        бронь истекает, вещь не должна сама вернуться в каталог.
        """
        from tests.test_scheduler import _SessionProxy
        monkeypatch.setattr(sched, "AsyncSessionLocal", lambda: _SessionProxy(db))

        product, listing = await _listed(db, category, seller)
        buyer = await user_factory(username="retry_withdrawn")
        created = await _checkout(db, buyer, product)

        await p2p_routes.withdraw_listing(listing.id, user=seller, db=db)

        order = await db.get(Order, uuid.UUID(created["order_id"]))
        order.created_at = datetime.utcnow() - timedelta(days=1)
        await db.commit()

        await sched.cleanup_reservations()
        await db.refresh(order)
        await db.refresh(product)

        assert order.status == OrderStatus.CANCELLED
        assert product.stock == 0

    async def test_cabinet_shows_reservation_and_sale(
        self, db, user_factory, category, seller,
    ):
        """
        Статус заявки говорит только о модерации — кабинет должен показать,
        что товар ждёт оплаты или уже продан, а не «В продаже».
        """
        reserved, _ = await _listed(db, category, seller, name="Ждёт оплаты")
        sold, _ = await _listed(db, category, seller, name="Продан")
        buyer = await user_factory(username="retry_cabinet")

        await _checkout(db, buyer, reserved)
        await _sold(db, sold, seller, user_factory)
        sold.stock = 0
        await db.commit()

        rows = {row["name"]: row for row in await p2p_routes.my_listings(user=seller, db=db)}

        assert rows["Ждёт оплаты"]["stock"] == 0
        assert rows["Ждёт оплаты"]["reserved"] == 1
        assert rows["Ждёт оплаты"]["reserved_until"].endswith("Z")
        assert rows["Продан"]["stock"] == 0
        assert rows["Продан"]["sold"] == 1
        assert rows["Продан"]["reserved"] == 0
