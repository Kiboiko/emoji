"""
Производительность: каталог постранично, кабинет продавца без лавины
запросов, индексы на горячих таблицах.

Тесты не меряют секунды — они фиксируют то, от чего зависит скорость при
росте данных: число строк в ответе и число запросов к базе.
"""

import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import Response
from sqlalchemy import event, text

from models.category import Category
from models.p2p import ListingImage, ListingStatus, ProductListing, SellerProfile
from models.product import Product
from routes import p2p
from routes import products as products_routes
from services import stock_service

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def category(db):
    row = Category(id=uuid.uuid4(), name_ru="Разное", name_en="Misc")
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def make_product(db, category):
    counter = 0

    async def make(name=None, description="описание", owner=None, **extra) -> Product:
        nonlocal counter
        counter += 1
        product = Product(
            id=uuid.uuid4(), name_ru=name or f"Товар {counter:03d}", name_en=name or f"Item {counter:03d}",
            description_ru=description, description_en=description,
            price_usdt=Decimal("10.00"), image_url="/uploads/products/placeholder.png",
            category_id=category.id, type="service", content_data={},
            owner_user_id=owner.id if owner else None, is_p2p=owner is not None,
            **extra,
        )
        db.add(product)
        await db.flush()
        return product
    return make


async def _page(db, **kwargs):
    response = Response()
    items = await products_routes.get_products(lang="ru", response=response, db=db, **kwargs)
    return items, response.headers["X-Has-More"]


# ---------------------------------------------------------------------------
# Каталог постранично
# ---------------------------------------------------------------------------

async def test_catalog_is_served_in_pages_without_gaps_or_repeats(db, make_product):
    for _ in range(7):
        await make_product()

    first, more_first = await _page(db, skip=0, limit=3)
    second, more_second = await _page(db, skip=3, limit=3)
    third, more_third = await _page(db, skip=6, limit=3)

    assert [len(first), len(second), len(third)] == [3, 3, 1]
    assert [more_first, more_second, more_third] == ["1", "1", "0"]
    ids = [p.id for p in first + second + third]
    assert len(set(ids)) == 7, "товар повторился или выпал между страницами"


async def test_exact_last_page_says_there_is_nothing_more(db, make_product):
    for _ in range(4):
        await make_product()

    items, more = await _page(db, skip=2, limit=2)

    assert len(items) == 2 and more == "0"


async def test_page_size_is_bounded(db, make_product):
    for _ in range(3):
        await make_product()

    huge, _ = await _page(db, limit=100000)
    zero, _ = await _page(db, limit=0)
    negative, _ = await _page(db, skip=-5, limit=2)

    assert len(huge) == 3          # потолок 100 не мешает маленькому каталогу
    assert len(zero) == 1          # хотя бы одна строка
    assert len(negative) == 2      # отрицательный сдвиг — это ноль


async def test_hits_come_first_across_pages(db, make_product):
    await make_product(name="Обычный 1")
    hit = await make_product(name="Хит", is_top=True)
    await make_product(name="Обычный 2")

    items, _ = await _page(db, limit=1)

    assert items[0].id == hit.id


async def test_search_looks_in_name_and_description_on_the_server(db, make_product):
    await make_product(name="Netflix", description="подписка на кино")
    await make_product(name="Spotify", description="музыка без рекламы")

    by_name, _ = await _page(db, search="netflix")
    by_description, _ = await _page(db, search="РЕКЛАМЫ")
    nothing, _ = await _page(db, search="zzz")

    assert [p.name for p in by_name] == ["Netflix"]
    assert [p.name for p in by_description] == ["Spotify"]
    assert nothing == []


async def test_search_treats_percent_and_underscore_literally(db, make_product):
    await make_product(name="Скидка 50% сегодня")
    await make_product(name="Обычный товар")

    percent, _ = await _page(db, search="%")
    underscore, _ = await _page(db, search="_")

    assert [p.name for p in percent] == ["Скидка 50% сегодня"]
    assert underscore == []


async def test_blank_search_returns_everything(db, make_product):
    await make_product()
    await make_product()

    items, _ = await _page(db, search="   ")

    assert len(items) == 2


# ---------------------------------------------------------------------------
# Кабинет продавца: число запросов не растёт с числом объявлений
# ---------------------------------------------------------------------------

@pytest.fixture
async def seller_user(db, user_factory):
    user = await user_factory(username="perf_seller")
    db.add(SellerProfile(
        id=uuid.uuid4(), user_id=user.id, display_name="Perf Shop",
        payout_wallet="UQPerf00000000001",
    ))
    await db.flush()
    return user


async def _approved_listing(db, seller_user, category, make_product, index):
    profile = (await db.execute(
        text("select id from seller_profiles where user_id = :u"), {"u": seller_user.id}
    )).scalar()
    product = await make_product(name=f"Лот {index}", owner=seller_user, stock=1, max_quantity=1)
    listing = ProductListing(
        id=uuid.uuid4(), seller_id=profile, product_id=product.id, category_id=category.id,
        name=f"Лот {index}", description="Описание лота", price_usd=Decimal("5.00"),
        status=ListingStatus.APPROVED,
    )
    db.add(listing)
    await db.flush()
    db.add(ListingImage(id=uuid.uuid4(), listing_id=listing.id, url=f"/uploads/listings/{index}.jpg"))
    await db.flush()
    return listing


async def _count_queries(db, coro_factory) -> int:
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    connection = db.bind.sync_connection
    event.listen(connection, "before_cursor_execute", record)
    try:
        await coro_factory()
    finally:
        event.remove(connection, "before_cursor_execute", record)
    return len(statements)


async def test_seller_cabinet_query_count_does_not_grow_with_listings(
    db, seller_user, category, make_product,
):
    for index in range(2):
        await _approved_listing(db, seller_user, category, make_product, index)
    # Прогрев: первый вызов один раз читает настройки в кеш процесса
    await p2p.my_listings(user=seller_user, db=db)
    few = await _count_queries(db, lambda: p2p.my_listings(user=seller_user, db=db))

    for index in range(2, 12):
        await _approved_listing(db, seller_user, category, make_product, index)
    many = await _count_queries(db, lambda: p2p.my_listings(user=seller_user, db=db))

    assert many == few, f"{few} запросов на 2 объявления и {many} на 12 — снова по запросу на объявление"


async def test_batched_sale_state_matches_the_single_item_functions(
    db, seller_user, category, make_product, user_factory, order_factory,
):
    from models.order import Order, OrderItem, OrderStatus
    from models.p2p import Deal, DealStatus

    listing = await _approved_listing(db, seller_user, category, make_product, 1)
    buyer = await user_factory(username="perf_buyer")

    # Одна единица бронируется неоплаченным заказом, одна уже продана сделкой
    pending_order = await order_factory(user=buyer, status=OrderStatus.PENDING)
    db.add(OrderItem(
        id=uuid.uuid4(), order_id=pending_order.id, product_id=listing.product_id,
        quantity=2, price_usdt=Decimal("5.00"), product_snapshot={},
    ))
    paid_order = await order_factory(user=buyer, status=OrderStatus.PAID)
    item = OrderItem(
        id=uuid.uuid4(), order_id=paid_order.id, product_id=listing.product_id,
        quantity=3, price_usdt=Decimal("5.00"), product_snapshot={},
    )
    db.add(item)
    await db.flush()
    db.add(Deal(
        id=uuid.uuid4(), order_id=paid_order.id, order_item_id=item.id, buyer_id=buyer.id,
        seller_id=seller_user.id, product_id=listing.product_id, product_name="Лот",
        amount_nano=1, commission_nano=0, status=DealStatus.CREATED,
    ))
    # Таймер и счётчик «Идентичности» у сделки заводит база
    await db.flush()

    batch = (await stock_service.sale_state_by_product(db, [listing.product_id]))[listing.product_id]

    assert batch["sold"] == await stock_service.units_sold(db, listing.product_id) == 3
    assert batch["reserved"] == await stock_service.units_reserved(db, listing.product_id) == 2
    assert batch["oldest_reservation"] == await stock_service.oldest_reservation(db, listing.product_id)
    assert batch["stock"] == 1


async def test_batched_sale_state_handles_empty_and_unknown_products(db):
    assert await stock_service.sale_state_by_product(db, []) == {}
    ghost = uuid.uuid4()
    state = (await stock_service.sale_state_by_product(db, [ghost]))[ghost]
    assert state == {"stock": None, "sold": 0, "reserved": 0, "oldest_reservation": None}


# ---------------------------------------------------------------------------
# Индексы
# ---------------------------------------------------------------------------

async def test_catalog_order_index_is_partial_and_matches_the_sort(db):
    """
    Индекс порядка каталога: без него каждая страница читает все активные
    товары. Он обязан совпадать с ORDER BY запроса, иначе база его не возьмёт.
    """
    definition = (await db.execute(text(
        "select indexdef from pg_indexes where indexname = 'ix_products_catalog_order'"
    ))).scalar()

    assert definition, "индекса порядка каталога нет в моделях"
    for part in ("is_top DESC", "sort_order DESC", "created_at DESC", "WHERE (is_active IS TRUE)"):
        assert part in definition, f"в индексе нет «{part}»: {definition}"


def _migration_indexes():
    path = next(Path(__file__).resolve().parent.parent.glob("alembic/versions/*_hot_path_indexes.py"))
    spec = importlib.util.spec_from_file_location("hot_path_indexes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.INDEXES


async def test_models_declare_every_index_the_migration_creates(db):
    """
    Миграция и модели не должны расходиться: иначе autogenerate предложит
    удалить индексы, а тестовая схема (она строится из моделей) не увидит их.
    """
    present = {
        row[0] for row in (await db.execute(text(
            "select indexname from pg_indexes where schemaname = 'public'"
        ))).all()
    }
    missing = [name for name, _table, _cols in _migration_indexes() if name not in present]
    assert not missing, f"в моделях нет индексов из миграции: {missing}"
