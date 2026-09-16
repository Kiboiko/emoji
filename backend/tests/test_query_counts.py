"""
Сторож против N+1.

Проверяет не скорость, а число запросов к базе: оно не должно расти вместе с
числом строк на странице. Замер времени на пустой тестовой базе ничего не
показал бы, а счётчик запросов ловит регрессию сразу — достаточно кому-то
обратиться к связанному объекту в цикле, и число подскочит.

Исходная версия списка заказов делала на каждый заказ отдельный запрос за
позициями и ещё один за пользователем: на странице в 50 заказов это 100
лишних обращений.
"""

import uuid
from contextlib import contextmanager
from decimal import Decimal

import pytest
from sqlalchemy import event

from models.order import OrderItem, OrderStatus
from routes import admin_orders, admin_users

pytestmark = pytest.mark.asyncio


@contextmanager
def count_queries(db):
    """Считает SQL-запросы, выполненные за время блока."""
    counter = {"n": 0}
    sync_engine = db.get_bind().engine

    def on_execute(*_args, **_kwargs):
        counter["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", on_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", on_execute)


async def _make_orders(db, order_factory, user_factory, count: int, items_each: int = 2):
    for index in range(count):
        buyer = await user_factory(username=f"load_buyer_{uuid.uuid4().hex[:8]}")
        order = await order_factory(buyer, total_usdt="10.00", status=OrderStatus.PAID)
        for position in range(items_each):
            db.add(OrderItem(
                id=uuid.uuid4(), order_id=order.id, product_id=None,
                product_snapshot={"name_ru": f"Товар {position}", "type": "digital"},
                quantity=1, price_usdt=Decimal("5.00"),
            ))
    await db.flush()


async def _orders_page(db, admin, limit):
    return await admin_orders.get_orders(
        status="all", search=None, date_from=None, date_to=None,
        skip=0, limit=limit, admin=admin, db=db,
    )


async def _users_page(db, admin, limit):
    return await admin_users.list_users(
        search=None, blocked=None, sort="created_at", order="desc",
        skip=0, limit=limit, _=admin, db=db,
    )


async def test_orders_list_query_count_is_constant(db, user_factory, order_factory):
    """
    Число запросов не зависит от размера страницы.

    Пять заказов и двадцать должны стоить одинаково: счёт, сами заказы,
    позиции одним запросом и пользователи одним запросом.
    """
    admin = await user_factory(username="qc_admin", is_admin=True)

    await _make_orders(db, order_factory, user_factory, count=5)
    with count_queries(db) as small:
        page_small = await _orders_page(db, admin, limit=50)

    await _make_orders(db, order_factory, user_factory, count=15)
    with count_queries(db) as large:
        page_large = await _orders_page(db, admin, limit=50)

    assert page_small["total"] == 5
    assert page_large["total"] == 20
    assert small["n"] == large["n"], (
        f"число запросов выросло с {small['n']} до {large['n']} — вернулся N+1"
    )
    # Ожидаем единицы запросов, а не десятки
    assert large["n"] <= 6, f"слишком много запросов на страницу: {large['n']}"


async def test_orders_items_loaded_in_one_query(db, user_factory, order_factory):
    """Позиции всех заказов страницы забираются одним запросом."""
    admin = await user_factory(username="qc_admin_2", is_admin=True)
    await _make_orders(db, order_factory, user_factory, count=10, items_each=3)

    with count_queries(db) as counter:
        page = await _orders_page(db, admin, limit=50)

    # 30 позиций по 10 заказам — и всё те же единицы запросов
    assert sum(len(o["items"]) for o in page["items"]) == 30
    assert counter["n"] <= 6


async def test_users_list_query_count_is_constant(db, user_factory, order_factory):
    """
    Счётчики заказов и рефералов считаются агрегатами.

    По запросу на строку списка вышло бы три обращения к базе на пользователя.
    """
    admin = await user_factory(username="qc_admin_3", is_admin=True)

    await _make_orders(db, order_factory, user_factory, count=3)
    with count_queries(db) as small:
        await _users_page(db, admin, limit=100)

    await _make_orders(db, order_factory, user_factory, count=12)
    with count_queries(db) as large:
        page = await _users_page(db, admin, limit=100)

    assert page["total"] >= 15
    assert small["n"] == large["n"], (
        f"число запросов выросло с {small['n']} до {large['n']} — вернулся N+1"
    )
    assert large["n"] <= 6


async def test_pagination_limits_work(db, user_factory, order_factory):
    """
    Страница не тянет всю таблицу.

    Прежние версии списков отдавали все строки разом; на боевых объёмах это
    минуты ожидания и мегабайты ответа.
    """
    admin = await user_factory(username="qc_admin_4", is_admin=True)
    await _make_orders(db, order_factory, user_factory, count=30)

    page = await _orders_page(db, admin, limit=10)

    assert page["total"] == 30
    assert len(page["items"]) == 10
