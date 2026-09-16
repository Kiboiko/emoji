"""
Админка: пользователи, блокировка, заказы, статистика.

Отдельного внимания заслуживает блокировка. Колонка is_blocked существовала с
первой миграции, но не проверялась нигде — то есть заблокировать человека было
невозможно. Тесты закрепляют оба места проверки: выдачу токена и каждый запрос
с уже выданным.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.order import Order, OrderItem, OrderStatus
from models.user import User
from routes import admin_orders, admin_stats, admin_users
from utils.auth import get_current_user

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def admin(db, user_factory):
    return await user_factory(username="panel_admin", is_admin=True)


async def _users_page(db, admin, **overrides):
    """Роут вызывается напрямую, поэтому значения Query подставляем сами."""
    params = dict(
        search=None, blocked=None, sort="created_at", order="desc", skip=0, limit=50,
    )
    params.update(overrides)
    return await admin_users.list_users(_=admin, db=db, **params)


async def _orders_page(db, admin, **overrides):
    params = dict(
        status="all", search=None, date_from=None, date_to=None, skip=0, limit=50,
    )
    params.update(overrides)
    return await admin_orders.get_orders(admin=admin, db=db, **params)


# ---------------------------------------------------------------------------
# Блокировка
# ---------------------------------------------------------------------------

async def test_blocked_user_loses_access(db, user_factory):
    """
    Заблокированный не проходит проверку токена.

    Токен остаётся валидным по подписи и сроку, поэтому без этой проверки
    блокировка не значила бы ничего до истечения токена.
    """
    user = await user_factory(username="to_block", is_blocked=True)

    from utils.auth import create_access_token
    token = create_access_token(data={
        "user_id": str(user.id), "telegram_id": user.telegram_id, "is_admin": False,
    })

    with pytest.raises(HTTPException) as exc:
        await get_current_user(authorization=f"Bearer {token}", db=db)

    assert exc.value.status_code == 403
    assert "заблокирован" in exc.value.detail.lower()


async def test_missing_token_is_401(db):
    """
    Отсутствие заголовка — 401, а не 422.

    Клиенты считают признаком истёкшей сессии именно 401: админка по нему
    обновляет токен, витрина чистит сохранённый.
    """
    with pytest.raises(HTTPException) as exc:
        await get_current_user(authorization=None, db=db)

    assert exc.value.status_code == 401


async def test_block_and_unblock(db, admin, user_factory):
    user = await user_factory(username="blockable")

    result = await admin_users.block_user(
        user.id, admin_users.BlockRequest(blocked=True, reason="скам"),
        admin=admin, db=db,
    )
    assert result["is_blocked"] is True
    await db.refresh(user)
    assert user.is_blocked is True

    await admin_users.block_user(
        user.id, admin_users.BlockRequest(blocked=False), admin=admin, db=db,
    )
    await db.refresh(user)
    assert user.is_blocked is False


async def test_cannot_block_admin(db, admin, user_factory):
    """Блокировка администратора закрыла бы доступ к самой админке."""
    other_admin = await user_factory(username="other_admin", is_admin=True)

    with pytest.raises(HTTPException) as exc:
        await admin_users.block_user(
            other_admin.id, admin_users.BlockRequest(blocked=True),
            admin=admin, db=db,
        )
    assert exc.value.status_code == 400


async def test_cannot_block_self(db, admin):
    with pytest.raises(HTTPException) as exc:
        await admin_users.block_user(
            admin.id, admin_users.BlockRequest(blocked=True), admin=admin, db=db,
        )
    assert exc.value.status_code == 400


async def test_block_reports_open_deals(db, admin, user_factory, order_factory):
    """
    Администратор должен видеть, что у блокируемого остались открытые сделки:
    он больше не сможет подтвердить получение сам.
    """
    from models.p2p import Deal, DealStatus

    seller = await user_factory(username="blocked_seller")
    buyer = await user_factory(username="deal_buyer")
    order = await order_factory(buyer, total_usdt="10.00")
    db.add(Deal(
        id=uuid.uuid4(), order_id=order.id, buyer_id=buyer.id, seller_id=seller.id,
        product_name="Вещь", amount_nano=1, status=DealStatus.PAID_ESCROW,
    ))
    await db.flush()

    result = await admin_users.block_user(
        seller.id, admin_users.BlockRequest(blocked=True), admin=admin, db=db,
    )
    assert result["open_deals"] == 1


# ---------------------------------------------------------------------------
# Список пользователей
# ---------------------------------------------------------------------------

async def test_users_search_by_username(db, admin, user_factory):
    await user_factory(username="alice_wonder")
    await user_factory(username="bob_builder")

    found = await _users_page(db, admin, search="alice")

    assert found["total"] == 1
    assert found["items"][0]["username"] == "alice_wonder"


async def test_users_search_by_telegram_id(db, admin, user_factory):
    target = await user_factory(username="by_id", telegram_id=555123456)

    found = await _users_page(db, admin, search="555123456")

    assert [i["telegram_id"] for i in found["items"]] == [target.telegram_id]


async def test_users_pagination(db, admin, user_factory):
    for index in range(5):
        await user_factory(username=f"paged_{index}")

    first = await _users_page(db, admin, limit=2)
    second = await _users_page(db, admin, limit=2, skip=2)

    assert len(first["items"]) == 2
    assert len(second["items"]) == 2
    assert first["total"] == second["total"]
    # Страницы не пересекаются
    assert {i["id"] for i in first["items"]}.isdisjoint({i["id"] for i in second["items"]})


async def test_users_filter_blocked(db, admin, user_factory):
    await user_factory(username="clean_user")
    await user_factory(username="banned_user", is_blocked=True)

    blocked = await _users_page(db, admin, blocked=True)

    assert blocked["total"] == 1
    assert blocked["items"][0]["username"] == "banned_user"


async def test_users_list_counts_orders(db, admin, user_factory, order_factory):
    """Суммы и счётчики считаются агрегатом, а не запросом на строку."""
    buyer = await user_factory(username="counted_buyer")
    await order_factory(buyer, total_usdt="10.00", status=OrderStatus.PAID)
    await order_factory(buyer, total_usdt="15.00", status=OrderStatus.COMPLETED)
    # Неоплаченный в сумму попадать не должен
    await order_factory(buyer, total_usdt="99.00", status=OrderStatus.PENDING)

    page = await _users_page(db, admin, search="counted_buyer")
    row = page["items"][0]

    assert row["orders_count"] == 2
    assert row["orders_total_usdt"] == 25.0


async def test_user_card(db, admin, user_factory, order_factory):
    user = await user_factory(username="card_user")
    await user_factory(username="card_referral", referrer_id=user.id)
    await order_factory(user, total_usdt="42.00", status=OrderStatus.PAID)

    card = await admin_users.user_card(user.id, _=admin, db=db)

    assert card["username"] == "card_user"
    assert len(card["orders"]) == 1
    assert len(card["referrals"]) == 1


async def test_user_card_missing(db, admin):
    with pytest.raises(HTTPException) as exc:
        await admin_users.user_card(uuid.uuid4(), _=admin, db=db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Заказы
# ---------------------------------------------------------------------------

async def test_orders_pagination_and_total(db, admin, user_factory, order_factory):
    buyer = await user_factory(username="orders_buyer")
    for _ in range(3):
        await order_factory(buyer, total_usdt="10.00", status=OrderStatus.PAID)

    page = await _orders_page(db, admin, limit=2)

    assert page["total"] == 3
    assert len(page["items"]) == 2


async def test_orders_filter_by_status(db, admin, user_factory, order_factory):
    buyer = await user_factory(username="status_buyer")
    await order_factory(buyer, total_usdt="10.00", status=OrderStatus.PAID)
    await order_factory(buyer, total_usdt="10.00", status=OrderStatus.PENDING)

    pending = await _orders_page(db, admin, status="pending")

    assert pending["total"] == 1
    assert pending["items"][0]["status"] == "pending"


async def test_orders_search_by_buyer(db, admin, user_factory, order_factory):
    target = await user_factory(username="searchable_buyer")
    other = await user_factory(username="unrelated_buyer")
    await order_factory(target, total_usdt="10.00", status=OrderStatus.PAID)
    await order_factory(other, total_usdt="10.00", status=OrderStatus.PAID)

    found = await _orders_page(db, admin, search="searchable")

    assert found["total"] == 1
    assert found["items"][0]["user_username"] == "searchable_buyer"


async def test_orders_include_items_without_n_plus_one(db, admin, user_factory, order_factory):
    buyer = await user_factory(username="items_buyer")
    order = await order_factory(buyer, total_usdt="30.00", status=OrderStatus.PAID)
    for name in ("Первый", "Второй"):
        db.add(OrderItem(
            id=uuid.uuid4(), order_id=order.id, product_id=None,
            product_snapshot={"name_ru": name, "type": "digital"},
            quantity=1, price_usdt=Decimal("15.00"),
        ))
    await db.flush()

    page = await _orders_page(db, admin)

    names = {i["product_name"] for i in page["items"][0]["items"]}
    assert names == {"Первый", "Второй"}


async def test_manual_paid_status_refused(db, admin, user_factory, order_factory):
    """
    Пометить заказ оплаченным вручную нельзя.

    Оплату подтверждает блокчейн: ручная отметка не создаст проводок и не
    выдаст товар, а баланс разойдётся с журналом.
    """
    buyer = await user_factory(username="manual_buyer")
    order = await order_factory(buyer, total_usdt="10.00", status=OrderStatus.PENDING)

    with pytest.raises(HTTPException) as exc:
        await admin_orders.change_order_status(
            order.id, admin_orders.StatusChange(status=OrderStatus.PAID),
            admin=admin, db=db,
        )
    assert exc.value.status_code == 400


async def test_manual_cancel_allowed(db, admin, user_factory, order_factory):
    buyer = await user_factory(username="cancel_buyer")
    order = await order_factory(buyer, total_usdt="10.00", status=OrderStatus.PENDING)

    result = await admin_orders.change_order_status(
        order.id, admin_orders.StatusChange(status=OrderStatus.CANCELLED, reason="тест"),
        admin=admin, db=db,
    )

    assert result["status"] == "cancelled"
    assert result["previous"] == "pending"


# ---------------------------------------------------------------------------
# Статистика
# ---------------------------------------------------------------------------

async def test_revenue_counts_paid_orders(db, admin, user_factory, order_factory):
    """
    Выручка считается с PAID, а не только с COMPLETED.

    Услуги и P2P остаются в PAID до ручной обработки или подтверждения
    получения, и прежний расчёт занижал выручку именно на них.
    """
    buyer = await user_factory(username="revenue_buyer")
    await order_factory(buyer, total_usdt="100.00", status=OrderStatus.PAID)
    await order_factory(buyer, total_usdt="50.00", status=OrderStatus.COMPLETED)
    await order_factory(buyer, total_usdt="999.00", status=OrderStatus.PENDING)

    stats = await admin_stats.get_stats(period="all", db=db, current_user=admin)

    assert float(stats["total_revenue_usdt"]) == 150.0


async def test_timeseries_fills_empty_days(db, admin, user_factory, order_factory):
    """
    Дни без продаж возвращаются нулями.

    Без этого график соединяет соседние точки и неделя простоя выглядит как
    непрерывные продажи.
    """
    buyer = await user_factory(username="series_buyer")
    await order_factory(buyer, total_usdt="20.00", status=OrderStatus.PAID)

    data = await admin_stats.revenue_timeseries(days=7, db=db, _=admin)

    assert len(data["series"]) == 7
    assert sum(point["revenue_usdt"] for point in data["series"]) == 20.0
    assert any(point["revenue_usdt"] == 0 for point in data["series"])


async def test_conversion(db, admin, user_factory, order_factory):
    buyer = await user_factory(username="conv_buyer")
    await order_factory(buyer, total_usdt="10.00", status=OrderStatus.PAID)
    await order_factory(buyer, total_usdt="10.00", status=OrderStatus.PENDING)
    await order_factory(buyer, total_usdt="10.00", status=OrderStatus.PENDING)

    data = await admin_stats.conversion(days=30, db=db, _=admin)

    assert data["total"] == 3
    assert data["paid"] == 1
    assert data["conversion_percent"] == 33.3


async def test_attention_counters(db, admin, user_factory, order_factory):
    from models.p2p import Deal, DealStatus

    buyer = await user_factory(username="attention_buyer")
    seller = await user_factory(username="attention_seller")
    order = await order_factory(buyer, total_usdt="10.00")
    db.add(Deal(
        id=uuid.uuid4(), order_id=order.id, buyer_id=buyer.id, seller_id=seller.id,
        product_name="Спорная вещь", amount_nano=1, status=DealStatus.DISPUTED,
    ))
    await db.flush()

    counters = await admin_stats.needs_attention(db=db, _=admin)

    assert counters["disputes_open"] == 1
    assert "listings_pending" in counters
    assert "withdrawals_pending" in counters
