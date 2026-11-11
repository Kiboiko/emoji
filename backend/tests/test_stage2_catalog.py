import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Response
from sqlalchemy import select

from database import get_db
from models.category import Category
from models.order import OrderItem, OrderStatus
from models.product import Product
from models.review import Review
from routes import categories, products
from schemas.category import CategoryCreate, CategoryUpdate
from services.catalog_service import CatalogSort

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def catalog(db):
    root = Category(name_ru="Root", name_en="Root")
    other = Category(name_ru="Other", name_en="Other")
    db.add_all([root, other])
    await db.flush()
    child = Category(name_ru="Child", name_en="Child", parent_id=root.id)
    db.add(child)
    await db.flush()

    async def make(category=child, **kwargs):
        product = Product(
            name_ru="Product", name_en="Product", description_ru="", description_en="",
            image_url="/image.png", price_usdt=Decimal(kwargs.pop("price", "10")),
            category_id=category.id, type="service", **kwargs,
        )
        db.add(product)
        await db.flush()
        return product
    return root, child, other, make


async def test_category_tree_validation_and_safe_delete(db, catalog):
    root, child, other, make = catalog
    for data in [
        CategoryUpdate(parent_id=root.id),  # self
        CategoryUpdate(parent_id=child.id),  # cycle/depth
        CategoryUpdate(parent_id=other.id),  # cannot move root with children
    ]:
        with pytest.raises(HTTPException) as exc:
            await categories.update_category(root.id, data, admin=None, db=db)
        assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await categories.create_category(CategoryCreate(name_ru="Third", name_en="Third", parent_id=child.id), admin=None, db=db)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await categories.delete_category(root.id, admin=None, db=db)
    assert exc.value.status_code == 409
    product = await make()
    with pytest.raises(HTTPException) as exc:
        await categories.delete_category(child.id, admin=None, db=db)
    assert exc.value.status_code == 409
    assert await db.get(Product, product.id) is product
    # Explicit null promotes child back to the root level.
    updated = await categories.update_category(child.id, CategoryUpdate(parent_id=None), admin=None, db=db)
    assert updated.parent_id is None
    await categories.delete_category(root.id, admin=None, db=db)
    assert await db.get(Category, root.id) is None


async def test_root_filter_includes_children_child_filter_does_not_include_root(db, catalog):
    root, child, other, make = catalog
    root_product, child_product = await make(root), await make(child)
    await make(other)
    root_rows = await products.get_products(category_id=root.id, db=db)
    child_rows = await products.get_products(category_id=child.id, db=db)
    assert {p.id for p in root_rows} == {root_product.id, child_product.id}
    assert [p.id for p in child_rows] == [child_product.id]


async def test_legacy_hidden_and_parent_field(db, catalog):
    root, child, _, _ = catalog
    db.add(Category(name_ru="Legacy", name_en="User items"))
    await db.flush()
    public = await categories.get_categories(lang="en", db=db)
    assert all(p.name != "User items" for p in public)
    assert next(p for p in public if p.id == child.id).parent_id == root.id
    assert any(p.name_en == "User items" for p in await categories.get_all_categories(admin=None, db=db))


async def test_price_sort_stable_pagination(db, catalog):
    _, _, _, make = catalog
    a = await make(price="5", id=uuid.UUID(int=1))
    b = await make(price="5", id=uuid.UUID(int=2))
    c = await make(price="20", id=uuid.UUID(int=3))
    response = Response()
    first = await products.get_products(sort=CatalogSort.PRICE_ASC, limit=1, response=response, db=db)
    assert [p.id for p in first] == [a.id]
    assert response.headers["X-Has-More"] == "1"
    second = await products.get_products(sort=CatalogSort.PRICE_ASC, skip=1, limit=2, db=db)
    assert [p.id for p in second] == [b.id, c.id]
    descending = await products.get_products(sort=CatalogSort.PRICE_DESC, db=db)
    assert [p.id for p in descending] == [c.id, a.id, b.id]


async def test_rating_window_matches_cards(db, catalog):
    _, _, _, make = catalog
    seller = await make(is_p2p=True)
    platform = await make()
    no_rating = await make()
    for product, rating, age, hidden in [
        (seller, 5, 45, False), (seller, 2, 1, False),
        (seller, 5, 1, True), (platform, 4, 45, False),
    ]:
        db.add(Review(product_id=product.id, rating=rating, text="review", is_hidden=hidden,
                      created_at=datetime.utcnow() - timedelta(days=age)))
    await db.flush()
    rows = await products.get_products(sort=CatalogSort.RATING, db=db)
    assert [p.id for p in rows] == [platform.id, seller.id, no_rating.id]
    assert [p.rating for p in rows] == [4, 3.5, None]


async def test_sales_sort_counts_quantity_only_completed(db, catalog, order_factory):
    _, _, _, make = catalog
    best, lower = await make(), await make()
    for product, quantity, status in [
        (best, 4, OrderStatus.COMPLETED), (lower, 2, OrderStatus.COMPLETED),
        (lower, 100, OrderStatus.CANCELLED), (lower, 100, OrderStatus.PAID),
    ]:
        order = await order_factory(status=status)
        db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=quantity,
                         price_usdt=Decimal("10"), product_snapshot={}))
    await db.flush()
    rows = await products.get_products(sort=CatalogSort.SALES, db=db)
    assert [p.id for p in rows] == [best.id, lower.id]


async def test_invalid_uuid_and_sort_return_422(db):
    app = FastAPI()
    app.include_router(categories.router)
    app.include_router(products.router)
    async def override():
        yield db
    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for url in ["/api/categories/bad", "/api/products/bad", "/api/products?category_id=bad",
                    "/api/products?sort=bad"]:
            assert (await client.get(url)).status_code == 422


async def test_promoted_shuffle_is_stable_and_explicit_price_remains_exact(db, catalog):
    from models.promotion import ProductPromotion
    _, _, _, make = catalog
    ordinary = await make(price="1")
    promoted = [await make(price=str(n)) for n in [8, 4, 6]]
    for product in promoted:
        db.add(ProductPromotion(product_id=product.id, promoted_until=datetime.utcnow() + timedelta(hours=1)))
    await db.flush()
    first = await products.get_products(sort=CatalogSort.DEFAULT, db=db)
    second = await products.get_products(sort=CatalogSort.DEFAULT, db=db)
    assert [p.id for p in first] == [p.id for p in second]
    assert {p.id for p in first[:3]} == {p.id for p in promoted}
    assert first[-1].id == ordinary.id
    paged = []
    for offset in range(0, 5, 2):
        page = await products.get_products(sort=CatalogSort.DEFAULT, skip=offset, limit=2, db=db)
        paged.extend(p.id for p in page)
    assert paged == [p.id for p in first]
    assert (await products.get_products(sort=CatalogSort.DEFAULT, skip=3, limit=1, db=db))[0].id == ordinary.id
    exact = await products.get_products(sort=CatalogSort.PRICE_ASC, db=db)
    assert [p.price_usdt for p in exact] == sorted(p.price_usdt for p in exact)
