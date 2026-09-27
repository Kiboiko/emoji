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


# ---------------------------------------------------------------------------
# Оценка товара в каталоге
# ---------------------------------------------------------------------------

async def test_catalog_carries_product_rating(db, product_factory, user_factory):
    """
    Оценка считалась только на странице товара — в сетке её не было вовсе.
    Средняя округляется до десятых, скрытые отзывы и отзывы без оценки не
    учитываются.
    """
    from models.review import Review

    buyer = await user_factory(username="reviewer")
    product = await product_factory(name="С отзывами")

    for value, hidden in [(5, False), (4, False), (1, True)]:
        db.add(Review(
            id=uuid.uuid4(), user_id=buyer.id, product_id=product.id,
            text="отзыв", rating=value, is_hidden=hidden,
        ))
    # Отзыв без оценки не должен тянуть среднее вниз
    db.add(Review(
        id=uuid.uuid4(), user_id=buyer.id, product_id=product.id,
        text="без оценки", rating=None,
    ))
    await db.flush()

    listed = await products_routes.get_products(db=db)
    found = [p for p in listed if p.id == product.id]
    assert found, "товар не попал в каталог"

    assert found[0].rating == 4.5
    assert found[0].reviews_count == 2


async def test_product_without_reviews_has_no_rating(db, product_factory):
    """Ноль звёзд хуже отсутствия звёзд: карточка не должна их рисовать."""
    product = await product_factory(name="Без отзывов")

    listed = await products_routes.get_products(db=db)
    item = [p for p in listed if p.id == product.id][0]

    assert item.rating is None
    assert item.reviews_count == 0


async def test_store_products_carry_the_same_fields_as_catalog(
    db, platform_store, product_factory, user_factory,
):
    """
    Витрина магазина отдаёт товары в том же виде, что и каталог.

    Своя урезанная выдача здесь уже однажды привела к тому, что экраны
    разошлись: в каталоге у карточки появились оценка и пометка хита, а на
    витрине осталась старая вёрстка без них.
    """
    from models.review import Review

    buyer = await user_factory(username="store_reviewer")
    product = await product_factory(name="С отзывами")
    product.is_top = True

    for value in (5, 4):
        db.add(Review(
            id=uuid.uuid4(), user_id=buyer.id, product_id=product.id,
            text="отзыв", rating=value,
        ))
    await db.flush()

    store = await stores.seller_store(platform_store.id, db=db)
    card = [p for p in store["products"] if p["id"] == str(product.id)][0]

    assert card["rating"] == 4.5
    assert card["reviews_count"] == 2
    assert card["is_top"] is True
    # Автор нужен карточке на обоих экранах одинаково
    assert card["author_kind"] == "platform"


# ---------------------------------------------------------------------------
# Список магазинов для главной
# ---------------------------------------------------------------------------

async def test_store_list_puts_platform_first(
    db, platform_store, product_factory, user_factory,
):
    """Площадка — лицо маркета, поэтому стоит первой, а не по алфавиту."""
    await product_factory(name="Товар площадки")

    owner = await user_factory(username="list_owner")
    db.add(SellerProfile(
        id=uuid.uuid4(), user_id=owner.id,
        display_name="Аптека", payout_wallet="UQListWallet0001",
    ))
    await db.flush()
    await product_factory(owner=owner, name="Чужой товар")

    listed = await stores.store_list(limit=12, db=db)

    assert [item["kind"] for item in listed][:1] == ["platform"]
    assert {item["name"] for item in listed} == {"Маркет", "Аптека"}


async def test_store_list_skips_stores_without_products(
    db, product_factory, user_factory,
):
    """
    Магазин без товаров не показываем: витрина, на которой нечего купить,
    разочаровывает ровно один раз.
    """
    seller_owner = await user_factory(username="has_goods")
    empty_owner = await user_factory(username="no_goods")

    db.add(SellerProfile(
        id=uuid.uuid4(), user_id=seller_owner.id,
        display_name="С товаром", payout_wallet="UQWithGoods00001",
    ))
    db.add(SellerProfile(
        id=uuid.uuid4(), user_id=empty_owner.id,
        display_name="Пустой", payout_wallet="UQNoGoods0000001",
    ))
    await db.flush()
    await product_factory(owner=seller_owner, name="Единственный")

    names = {item["name"] for item in await stores.store_list(limit=12, db=db)}

    assert "С товаром" in names
    assert "Пустой" not in names


async def test_store_list_skips_banned_seller(db, product_factory, user_factory):
    owner = await user_factory(username="banned_in_list")
    db.add(SellerProfile(
        id=uuid.uuid4(), user_id=owner.id,
        display_name="Закрыто", payout_wallet="UQBannedList0001",
        status=SellerStatus.BANNED,
    ))
    await db.flush()
    await product_factory(owner=owner, name="Товар заблокированного")

    names = {item["name"] for item in await stores.store_list(limit=12, db=db)}
    assert "Закрыто" not in names


async def test_store_list_counts_only_active_products(
    db, product_factory, user_factory,
):
    owner = await user_factory(username="counts_owner")
    db.add(SellerProfile(
        id=uuid.uuid4(), user_id=owner.id,
        display_name="Считаем", payout_wallet="UQCounting000001",
    ))
    await db.flush()
    await product_factory(owner=owner, name="Живой")
    await product_factory(owner=owner, name="Снятый", active=False)

    listed = await stores.store_list(limit=12, db=db)
    mine = [item for item in listed if item["name"] == "Считаем"]

    assert mine, "магазин не попал в список"
    assert mine[0]["products"] == 1


def _add_review(db, buyer, product, rating: int, hidden: bool = False) -> None:
    """Отзыв на товар. Своя функция, потому что общей фикстуры в наборе нет."""
    from models.review import Review
    db.add(Review(
        id=uuid.uuid4(), user_id=buyer.id, product_id=product.id,
        text="отзыв", rating=rating, is_hidden=hidden,
    ))

# ---------------------------------------------------------------------------
# Оценка магазина
# ---------------------------------------------------------------------------

async def test_store_rating_counts_product_reviews(
    db, user_factory, product_factory,
):
    """
    Раньше в шапку шёл счётчик из seller_profiles: он растёт только от
    отзывов по сделкам P2P, а обычная покупка сделкой не оформляется — и у
    магазина с отзывами на карточках рейтинг оставался пустым.
    """
    owner = await user_factory(username="rated_owner")
    seller = SellerProfile(
        id=uuid.uuid4(), user_id=owner.id,
        display_name="С отзывами", payout_wallet="UQRated000000001",
    )
    db.add(seller)
    await db.flush()

    buyer = await user_factory(username="rated_buyer")
    product = await product_factory(owner=owner, name="Товар с отзывами")
    _add_review(db, buyer, product, 5)
    _add_review(db, buyer, product, 4)
    await db.flush()

    store = await stores.seller_store(seller.id, db=db)

    assert store["rating"] == 4.5
    assert store["rating_count"] == 2


async def test_store_rating_ignores_hidden_reviews(
    db, user_factory, product_factory,
):
    owner = await user_factory(username="hidden_owner")
    seller = SellerProfile(
        id=uuid.uuid4(), user_id=owner.id,
        display_name="Со скрытым", payout_wallet="UQHidden00000001",
    )
    db.add(seller)
    await db.flush()

    buyer = await user_factory(username="hidden_buyer")
    product = await product_factory(owner=owner, name="Товар")
    _add_review(db, buyer, product, 5)
    _add_review(db, buyer, product, 1, hidden=True)
    await db.flush()

    store = await stores.seller_store(seller.id, db=db)

    assert store["rating"] == 5.0
    assert store["rating_count"] == 1


async def test_store_rating_counts_withdrawn_products_too(
    db, user_factory, product_factory,
):
    """
    Отзыв на товар, который продавец потом снял, говорит о продавце ровно
    столько же: для витрины берутся живые товары, для оценки — все.
    """
    owner = await user_factory(username="withdrawn_owner")
    seller = SellerProfile(
        id=uuid.uuid4(), user_id=owner.id,
        display_name="Со снятым", payout_wallet="UQWithdrawn00001",
    )
    db.add(seller)
    await db.flush()

    buyer = await user_factory(username="withdrawn_buyer")
    gone = await product_factory(owner=owner, name="Снятый", active=False)
    _add_review(db, buyer, gone, 3)
    await db.flush()

    store = await stores.seller_store(seller.id, db=db)

    assert store["rating"] == 3.0
    assert store["rating_count"] == 1
    assert store["products"] == [], "снятый товар не должен быть на витрине"


async def test_store_without_reviews_has_no_rating(db, user_factory, product_factory):
    """Пустые звёзды читаются как нулевая оценка — лучше не показывать вовсе."""
    owner = await user_factory(username="quiet_owner")
    seller = SellerProfile(
        id=uuid.uuid4(), user_id=owner.id,
        display_name="Без отзывов", payout_wallet="UQQuiet000000001",
    )
    db.add(seller)
    await db.flush()
    await product_factory(owner=owner, name="Товар")

    store = await stores.seller_store(seller.id, db=db)

    assert store["rating"] is None
    assert store["rating_count"] == 0


async def test_store_list_has_no_channels(db, user_factory, product_factory):
    """
    Витрина у канала есть, но в строке «Магазины» он читался как ещё один
    продавец: завёл подписку — и оказался среди магазинов.
    """
    author = await user_factory(username="list_channel_owner")
    channel = Channel(
        id=uuid.uuid4(), owner_user_id=author.id,
        telegram_chat_id=-1007777777777, title="Канал в списке",
        status=ChannelStatus.ACTIVE, bot_is_admin=True,
        payout_wallet="EQChannelList001",
    )
    db.add(channel)
    await db.flush()

    plan_product = await product_factory(type_="subscription", name="Канал — месяц")
    db.add(SubscriptionPlan(
        id=uuid.uuid4(), channel_id=channel.id, product_id=plan_product.id,
        title_ru="Месяц", title_en="Month", duration_days=30,
        price_usd=Decimal("5.00"),
    ))
    await db.flush()

    listed = await stores.store_list(limit=12, db=db)

    assert all(item["kind"] != "channel" for item in listed)
    assert "Канал в списке" not in {item["name"] for item in listed}


async def test_author_rating_matches_the_storefront(
    db, user_factory, product_factory,
):
    """
    На странице товара продавец показывается той же строкой, что и на своей
    витрине. Раньше туда шёл счётчик из seller_profiles — он растёт только
    от отзывов по сделкам, и числа расходились.
    """
    owner = await user_factory(username="same_rating_owner")
    seller = SellerProfile(
        id=uuid.uuid4(), user_id=owner.id,
        display_name="Одинаково", payout_wallet="UQSameRating0001",
    )
    db.add(seller)
    await db.flush()

    buyer = await user_factory(username="same_rating_buyer")
    product = await product_factory(owner=owner, name="Товар")
    _add_review(db, buyer, product, 4)
    _add_review(db, buyer, product, 5)
    await db.flush()

    page = await products_routes.get_product(str(product.id), db=db)
    store = await stores.seller_store(seller.id, db=db)

    assert page.author_rating == store["rating"] == 4.5
    assert page.author_reviews == store["rating_count"] == 2


async def test_subscription_lives_in_the_author_store(db, user_factory, product_factory):
    """
    Подписка продаётся магазином автора, а не отдельным магазином-каналом.

    Раньше товар тарифа всегда приходил от канала: у автора, который продаёт
    что-то ещё, магазинов оказывалось два сразу — свой и «канал».
    """
    author = await user_factory(username="sub_store_owner")
    seller = SellerProfile(
        id=uuid.uuid4(), user_id=author.id,
        display_name="Мой маркет", payout_wallet="EQSubStore0000000",
    )
    db.add(seller)

    channel = Channel(
        id=uuid.uuid4(), owner_user_id=author.id,
        telegram_chat_id=-1006666666666, title="Закрытый канал",
        status=ChannelStatus.ACTIVE, bot_is_admin=True,
        payout_wallet="EQSubStore0000000",
    )
    db.add(channel)
    await db.flush()

    sub_product = await product_factory(
        type_="subscription", name="Закрытый канал — месяц", owner=author,
    )
    # Владелец у подписки есть, а эскроу нет: доступ выдаёт бот, сделка не
    # заводится. Фабрика ставит is_p2p по наличию владельца — поправляем.
    sub_product.is_p2p = False
    db.add(SubscriptionPlan(
        id=uuid.uuid4(), channel_id=channel.id, product_id=sub_product.id,
        title_ru="Месяц", title_en="Month", duration_days=30,
        price_usd=Decimal("5.00"),
    ))
    await db.flush()

    store = await stores.seller_store(seller.id, db=db)
    card = next(p for p in store["products"] if p["id"] == str(sub_product.id))

    assert card["author_kind"] == "seller"
    assert card["author_name"] == "Мой маркет"

    # И в строке «Магазины» автор стоит один раз, а не дважды
    listed = await stores.store_list(limit=12, db=db)
    assert [item["name"] for item in listed].count("Мой маркет") == 1
