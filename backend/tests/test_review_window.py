"""
Отзывы о продавцах — только за последние 30 дней.

Окно ограничивает то, что видит покупатель и что идёт в среднюю оценку;
сами отзывы остаются в базе. Отзывы на товары площадки под окно не попадают.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from models.category import Category
from models.p2p import SellerProfile
from models.product import Product
from models.review import Review
from routes import p2p, reviews, stores
from routes import products as products_routes
from services import review_service, settings_service

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def category(db):
    row = Category(id=uuid.uuid4(), name_ru="Разное", name_en="Misc")
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def seller(db, user_factory):
    owner = await user_factory(username="window_owner")
    row = SellerProfile(
        id=uuid.uuid4(), user_id=owner.id,
        display_name="Window Shop", payout_wallet="UQWindow000000001",
    )
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def make_product(db, category):
    async def make(owner_id=None):
        product = Product(
            id=uuid.uuid4(), name_ru="Товар", name_en="Item",
            description_ru="описание", description_en="description",
            price_usdt=Decimal("10.00"), image_url="/uploads/products/placeholder.png",
            category_id=category.id, type="service", owner_user_id=owner_id,
            is_p2p=owner_id is not None, content_data={},
        )
        db.add(product)
        await db.flush()
        return product
    return make


async def _review(db, buyer, product, rating, days_ago, hidden=False):
    db.add(Review(
        id=uuid.uuid4(), user_id=buyer.id, product_id=product.id, text="отзыв",
        rating=rating, is_hidden=hidden,
        created_at=datetime.utcnow() - timedelta(days=days_ago),
    ))
    await db.flush()


async def test_old_reviews_do_not_count_towards_store_rating(
    db, seller, make_product, user_factory,
):
    buyer = await user_factory(username="window_buyer")
    product = await make_product(seller.user_id)
    await _review(db, buyer, product, 5, days_ago=2)
    await _review(db, buyer, product, 3, days_ago=29)
    await _review(db, buyer, product, 1, days_ago=45)      # вне окна
    await _review(db, buyer, product, 1, days_ago=400)     # вне окна

    store = await stores.seller_store(seller.id, db=db)

    assert store["rating_count"] == 2
    assert store["rating"] == 4.0


async def test_seller_without_recent_reviews_has_no_rating(
    db, seller, make_product, user_factory,
):
    buyer = await user_factory(username="window_buyer2")
    product = await make_product(seller.user_id)
    await _review(db, buyer, product, 5, days_ago=90)

    store = await stores.seller_store(seller.id, db=db)

    assert store["rating"] is None and store["rating_count"] == 0


async def test_old_reviews_are_not_listed_on_seller_product(
    db, seller, make_product, user_factory,
):
    buyer = await user_factory(username="window_buyer3")
    product = await make_product(seller.user_id)
    await _review(db, buyer, product, 5, days_ago=3)
    await _review(db, buyer, product, 2, days_ago=60)

    shown = await reviews.get_reviews(product_id=str(product.id), db=db)

    assert [r.rating for r in shown] == [5]


async def test_platform_product_reviews_ignore_the_window(
    db, make_product, user_factory,
):
    """Отзыв на товар площадки — не отзыв о продавце: он живёт вечно."""
    buyer = await user_factory(username="window_buyer4")
    product = await make_product(owner_id=None)
    await _review(db, buyer, product, 4, days_ago=200)

    shown = await reviews.get_reviews(product_id=str(product.id), db=db)

    assert [r.rating for r in shown] == [4]


async def test_catalog_card_rating_uses_the_window_only_for_sellers(
    db, seller, make_product, user_factory,
):
    buyer = await user_factory(username="window_buyer5")
    mine = await make_product(seller.user_id)
    platform_item = await make_product(owner_id=None)
    await _review(db, buyer, mine, 5, days_ago=1)
    await _review(db, buyer, mine, 1, days_ago=100)
    await _review(db, buyer, platform_item, 2, days_ago=100)

    ratings = await products_routes._ratings_by_product(db, [mine, platform_item])

    assert ratings[mine.id] == {"rating": 5.0, "reviews_count": 1}
    assert ratings[platform_item.id] == {"rating": 2.0, "reviews_count": 1}


async def test_window_is_configurable_and_zero_means_forever(
    db, seller, make_product, user_factory,
):
    buyer = await user_factory(username="window_buyer6")
    product = await make_product(seller.user_id)
    await _review(db, buyer, product, 5, days_ago=45)

    assert (await stores.seller_store(seller.id, db=db))["rating_count"] == 0

    await settings_service.set_setting(db, "seller_reviews_window_days", 60)
    assert (await stores.seller_store(seller.id, db=db))["rating_count"] == 1

    await settings_service.set_setting(db, "seller_reviews_window_days", 0)
    assert await review_service.window_cutoff(db) is None
    assert (await stores.seller_store(seller.id, db=db))["rating_count"] == 1


async def test_seller_ratings_one_query_for_many_sellers(
    db, seller, make_product, user_factory,
):
    other_owner = await user_factory(username="window_other")
    db.add(SellerProfile(
        id=uuid.uuid4(), user_id=other_owner.id,
        display_name="Other Shop", payout_wallet="UQOther0000000001",
    ))
    await db.flush()
    buyer = await user_factory(username="window_buyer7")
    await _review(db, buyer, await make_product(seller.user_id), 5, days_ago=1)
    await _review(db, buyer, await make_product(other_owner.id), 3, days_ago=1)
    await _review(db, buyer, await make_product(other_owner.id), 1, days_ago=80)

    ratings = await review_service.seller_ratings(db, [seller.user_id, other_owner.id])

    assert ratings[seller.user_id] == (5.0, 1)
    assert ratings[other_owner.id] == (3.0, 1)


async def test_own_cabinet_shows_the_same_rating_as_the_storefront(
    db, seller, make_product, user_factory,
):
    from models.user import User
    buyer = await user_factory(username="window_buyer8")
    product = await make_product(seller.user_id)
    await _review(db, buyer, product, 4, days_ago=5)
    await _review(db, buyer, product, 1, days_ago=50)
    owner = await db.get(User, seller.user_id)

    cabinet = await p2p.seller_profile(user=owner, db=db)

    assert cabinet["rating"] == 4.0 and cabinet["rating_count"] == 1
