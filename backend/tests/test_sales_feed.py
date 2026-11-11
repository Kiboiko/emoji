from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI

from database import get_db
from models.category import Category
from models.order import Order, OrderItem, OrderStatus
from models.p2p import Deal, DealStatus, SellerProfile
from models.product import Product
from routes.sales_feed import get_sales_feed, router

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def sales(db, order_factory, user_factory):
    seller = await user_factory()
    profile = SellerProfile(user_id=seller.id, display_name="Shop", payout_wallet="wallet")
    root = Category(name_ru="Root", name_en="Root")
    db.add_all([profile, root])
    await db.flush()
    child = Category(name_ru="Child", name_en="Child", parent_id=root.id)
    db.add(child)
    await db.flush()
    product = Product(name_ru="Current", name_en="Current", description_ru="", description_en="",
                      image_url="/current.png", price_usdt=Decimal("999"), category_id=child.id, type="service")
    db.add(product)
    await db.flush()
    async def make(status=OrderStatus.COMPLETED, deal_status=None, quantity=2, deleted=False, p2p=False,
                   order_times=None, released_at=None):
        order = await order_factory(status=status, **{"paid_at": datetime.utcnow(), **(order_times or {})})
        snapshot = {
            "name_ru": "Purchased", "name_en": "Bought", "image_url": "/purchased.png",
            "is_p2p": p2p or deal_status is not None, "owner_user_id": str(seller.id),
            "content_data": {"secret": "never-public"},
        }
        item = OrderItem(order_id=order.id, product_id=None if deleted else product.id,
                         quantity=quantity, price_usdt=Decimal("3.25"), product_snapshot=snapshot,
                         user_data={"login": "private"})
        db.add(item)
        await db.flush()
        if deal_status is not None:
            db.add(Deal(order_id=order.id, order_item_id=item.id, buyer_id=order.user_id,
                        seller_id=seller.id, product_id=product.id, product_name="Sale",
                        status=deal_status, released_at=(released_at or datetime.utcnow()) if deal_status == DealStatus.RELEASED else None))
            await db.flush()
        return item
    return root, child, product, profile, make


async def test_only_completed_settled_sales_and_public_snapshot_fields(db, sales):
    _, _, _, profile, make = sales
    ordinary = await make()
    released = await make(deal_status=DealStatus.RELEASED)
    for status in [OrderStatus.PENDING, OrderStatus.PAID, OrderStatus.CANCELLED]:
        await make(status=status)
    for status in [DealStatus.REFUNDED, DealStatus.PAID_ESCROW, DealStatus.DISPUTED, DealStatus.CANCELLED]:
        await make(deal_status=status)
    await make(p2p=True)  # broken legacy P2P without settlement is not a completed sale
    result = await get_sales_feed(db=db, lang="en")
    assert {i.id for i in result.items} == {ordinary.id, released.id}
    for item in result.items:
        assert item.name == "Bought" and item.image_url == "/purchased.png"
        assert item.total_usd == Decimal("6.50")
        assert item.store_name == "Shop" and item.store_slug == f"seller/{profile.id}"
        assert set(item.model_dump()) == {"id", "product_id", "name", "image_url", "quantity",
                                          "total_usd", "store_name", "store_slug", "completed_at"}
    assert "private" not in result.model_dump_json() and "never-public" not in result.model_dump_json()


async def test_paging_category_hierarchy_and_deleted_history(db, sales):
    root, child, product, _, make = sales
    live = await make()
    deleted = await make(deleted=True)
    global_rows = await get_sales_feed(db=db, limit=1)
    assert len(global_rows.items) == 1 and global_rows.has_more
    next_rows = await get_sales_feed(db=db, limit=1, skip=1)
    assert len(next_rows.items) == 1 and not next_rows.has_more
    assert {i.id for i in global_rows.items + next_rows.items} == {live.id, deleted.id}
    for category in [root, child]:
        filtered = await get_sales_feed(db=db, category_id=category.id)
        assert [i.id for i in filtered.items] == [live.id]
    full = await get_sales_feed(db=db)
    assert next(i for i in full.items if i.id == deleted.id).product_id is None


async def test_sales_sort_and_feed_share_settlement_filter(db, sales):
    from routes.products import get_products
    from services.catalog_service import CatalogSort
    _, _, product, _, make = sales
    await make(deal_status=DealStatus.RELEASED, quantity=2)
    await make(deal_status=DealStatus.REFUNDED, quantity=100)
    # This also exercises correlation of the nested deal predicates in sales sorting.
    rows = await get_products(sort=CatalogSort.SALES, db=db)
    assert rows[0].id == product.id
    assert len((await get_sales_feed(db=db)).items) == 1


async def test_feed_invalid_category_uuid_is_422(db):
    app = FastAPI()
    app.include_router(router)
    async def override():
        yield db
    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/sales-feed?category_id=bad")).status_code == 422


@pytest.fixture
def feed_now(monkeypatch):
    import routes.sales_feed as feed
    now = datetime(2026, 11, 4, 10, 0)

    class FrozenDateTime(datetime):
        @classmethod
        def utcnow(cls):
            return now

    monkeypatch.setattr(feed, "datetime", FrozenDateTime)
    return now


async def test_feed_expires_at_14_days_before_paging_without_deleting_orders(db, sales, feed_now):
    root, _, _, _, make = sales
    cutoff = feed_now - timedelta(days=14)
    expired = await make(order_times={"paid_at": cutoff})
    older = await make(order_times={"paid_at": cutoff - timedelta(microseconds=1)})
    boundary = await make(order_times={"paid_at": cutoff + timedelta(microseconds=1)})
    latest = await make(order_times={"paid_at": feed_now})
    await make(order_times={"paid_at": feed_now + timedelta(seconds=1)})

    first = await get_sales_feed(db=db, limit=1)
    second = await get_sales_feed(db=db, limit=1, skip=1)
    assert [s.id for s in first.items] == [latest.id] and first.has_more
    assert [s.id for s in second.items] == [boundary.id] and not second.has_more
    assert {s.id for s in (await get_sales_feed(db=db, category_id=root.id)).items} == {latest.id, boundary.id}
    for item in [expired, older]:
        assert await db.get(OrderItem, item.id) is not None
        assert (await db.get(Order, item.order_id)).status == OrderStatus.COMPLETED


async def test_feed_retention_uses_release_time_for_old_escrow_orders(db, sales, feed_now):
    _, _, _, _, make = sales
    old_payment = feed_now - timedelta(days=30)
    fresh = await make(deal_status=DealStatus.RELEASED, order_times={"paid_at": old_payment},
                       released_at=feed_now - timedelta(days=1))
    await make(deal_status=DealStatus.RELEASED, order_times={"paid_at": feed_now},
               released_at=feed_now - timedelta(days=15))
    assert [s.id for s in (await get_sales_feed(db=db)).items] == [fresh.id]


async def test_feed_retention_legacy_order_without_payment_time(db, sales, feed_now):
    _, _, _, _, make = sales
    fresh = await make(order_times={"paid_at": None, "created_at": feed_now - timedelta(days=13)})
    await make(order_times={"paid_at": None, "created_at": feed_now - timedelta(days=15)})
    assert [s.id for s in (await get_sales_feed(db=db)).items] == [fresh.id]
