"""
Витрины магазинов: у каждого товара есть продавец, включая саму площадку.

До этой правки «товар площадки» — это товар без владельца, и лица у него не
было вовсе: в каталоге он приходил без автора, а страницы, на которую можно
перейти, не существовало.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from models.category import Category
from models.p2p import SellerProfile, SellerStatus
from models.product import Product
from models.subscription import Channel, ChannelStatus, SubscriptionPlan
from routes import products as products_routes
from routes import stores

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def category(db):
    row = Category(id=uuid.uuid4(), name_ru="Разное", name_en="Misc")
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def platform_store(db):
    """
    На проде эту строку заводит миграция. В тестах схема создаётся из
    моделей, поэтому магазин площадки собираем здесь.
    """
    store = SellerProfile(
        id=uuid.uuid4(),
        user_id=None,
        display_name="Маркет",
        payout_wallet="",
        description="Товары от площадки",
        is_platform=True,
    )
    db.add(store)
    await db.flush()
    return store


@pytest.fixture
async def product_factory(db, category):
    # Тип service намеренно: digital каталог отдаёт, только если под него
    # есть непроданные ключи, а здесь проверяется не наличие товара
    async def make(*, owner=None, type_="service", active=True, name="Товар") -> Product:
        product = Product(
            id=uuid.uuid4(),
            name_ru=name, name_en=name,
            description_ru="описание", description_en="description",
            price_usdt=Decimal("10.00"),
            image_url="/uploads/products/placeholder.png",
            category_id=category.id,
            type=type_,
            owner_user_id=owner.id if owner else None,
            is_p2p=owner is not None,
            is_active=active,
            content_data={},
        )
        db.add(product)
        await db.flush()
        return product
    return make


# ---------------------------------------------------------------------------
# Магазин площадки
# ---------------------------------------------------------------------------

async def test_platform_product_gets_the_platform_store(db, platform_store, product_factory):
    """Товар без владельца продаёт не «никто», а площадка."""
    product = await product_factory()

    listed = await products_routes.get_products(db=db)
    found = [p for p in listed if p.id == product.id]
    assert found, "товар не попал в каталог"
    item = found[0]

    assert item.author_kind == "platform"
    assert item.author_id == platform_store.id
    assert item.author_name == "Маркет"


async def test_platform_store_lists_its_products(db, platform_store, product_factory):
    mine = await product_factory(name="Ключ Netflix")
    hidden = await product_factory(name="Снятый", active=False)

    store = await stores.seller_store(platform_store.id, db=db)

    assert store["kind"] == "platform"
    ids = {p["id"] for p in store["products"]}
    assert str(mine.id) in ids
    assert str(hidden.id) not in ids, "снятый с продажи товар попал на витрину"


async def test_platform_store_excludes_subscriptions(
    db, platform_store, product_factory, user_factory,
):
    """
    У товара подписки владельца тоже нет, но продаёт его канал автора, а не
    площадка. Без этого отсечения чужие подписки висели бы в её витрине.
    """
    author = await user_factory(username="sub_author")
    channel = Channel(
        id=uuid.uuid4(), owner_user_id=author.id,
        telegram_chat_id=-1009999999999, title="Канал",
        status=ChannelStatus.ACTIVE, bot_is_admin=True,
        payout_wallet="EQWallet00000000",
    )
    db.add(channel)
    await db.flush()

    sub_product = await product_factory(type_="subscription", name="Канал — месяц")
    db.add(SubscriptionPlan(
        id=uuid.uuid4(), channel_id=channel.id, product_id=sub_product.id,
        title_ru="Месяц", title_en="Month", duration_days=30,
        price_usd=Decimal("5.00"),
    ))
    await db.flush()

    store = await stores.seller_store(platform_store.id, db=db)
    assert str(sub_product.id) not in {p["id"] for p in store["products"]}


# ---------------------------------------------------------------------------
# Магазин продавца
# ---------------------------------------------------------------------------

async def test_seller_store_shows_only_own_products(db, user_factory, product_factory):
    owner = await user_factory(username="shop_owner")
    stranger = await user_factory(username="other_owner")

    seller = SellerProfile(
        id=uuid.uuid4(), user_id=owner.id,
        display_name="Часы и ремешки", payout_wallet="UQSellerWallet00",
        description="Только оригиналы", is_verified=True,
    )
    db.add(seller)
    await db.flush()

    mine = await product_factory(owner=owner, name="Casio")
    theirs = await product_factory(owner=stranger, name="Чужое")

    store = await stores.seller_store(seller.id, db=db)

    assert store["kind"] == "seller"
    assert store["name"] == "Часы и ремешки"
    assert store["is_verified"] is True
    assert store["description"] == "Только оригиналы"

    ids = {p["id"] for p in store["products"]}
    assert str(mine.id) in ids
    assert str(theirs.id) not in ids


async def test_banned_seller_store_is_hidden(db, user_factory):
    """
    Товары заблокированного продавца и так сняты, а живая страница создавала
    бы впечатление работающего магазина.
    """
    owner = await user_factory(username="banned_owner")
    seller = SellerProfile(
        id=uuid.uuid4(), user_id=owner.id,
        display_name="Закрыто", payout_wallet="UQBanned00000000",
        status=SellerStatus.BANNED,
    )
    db.add(seller)
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await stores.seller_store(seller.id, db=db)
    assert exc.value.status_code == 404


async def test_unknown_store_is_not_found(db):
    with pytest.raises(HTTPException) as exc:
        await stores.seller_store(uuid.uuid4(), db=db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Витрина канала
# ---------------------------------------------------------------------------

async def test_channel_store_lists_its_plans(db, user_factory, product_factory):
    author = await user_factory(username="channel_owner")
    channel = Channel(
        id=uuid.uuid4(), owner_user_id=author.id,
        telegram_chat_id=-1008888888888, title="Закрытый канал",
        description="Про инвестиции", status=ChannelStatus.ACTIVE,
        bot_is_admin=True, payout_wallet="EQChannel0000000", is_verified=True,
    )
    db.add(channel)
    await db.flush()

    product = await product_factory(type_="subscription", name="Закрытый канал — месяц")
    db.add(SubscriptionPlan(
        id=uuid.uuid4(), channel_id=channel.id, product_id=product.id,
        title_ru="Месяц", title_en="Month", duration_days=30,
        price_usd=Decimal("5.00"),
    ))
    await db.flush()

    store = await stores.channel_store(channel.id, db=db)

    assert store["kind"] == "channel"
    assert store["name"] == "Закрытый канал"
    assert store["is_verified"] is True
    # Рейтинга у канала нет: отзывы собираются по сделкам, а подписка идёт
    # не через сделку
    assert store["rating"] is None
    assert {p["id"] for p in store["products"]} == {str(product.id)}


async def test_unpublished_channel_store_is_hidden(db, user_factory):
    author = await user_factory(username="draft_owner")
    channel = Channel(
        id=uuid.uuid4(), owner_user_id=author.id,
        telegram_chat_id=-1007777777777, title="Черновик",
        status=ChannelStatus.DRAFT, bot_is_admin=True,
        payout_wallet="EQDraft000000000",
    )
    db.add(channel)
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await stores.channel_store(channel.id, db=db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Каталог без магазина площадки
# ---------------------------------------------------------------------------

async def test_catalog_survives_without_platform_store(db, product_factory):
    """
    Строку магазина площадки заводит миграция. Если её нет, каталог должен
    работать по-старому, а не падать: создавать её на GET-запросе нельзя.
    """
    product = await product_factory()

    listed = await products_routes.get_products(db=db)
    found = [p for p in listed if p.id == product.id]
    assert found, "товар не попал в каталог"
    item = found[0]

    assert item.author_kind is None
    assert item.author_id is None
