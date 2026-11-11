"""Shared category filtering and deterministic catalog ordering."""
from datetime import datetime
from enum import Enum
from sqlalchemy import exists, func, or_, select, case, cast, String

from models.category import Category
from models.order import Order, OrderItem, OrderStatus
from models.p2p import Deal, DealStatus
from models.product import Product
from models.review import Review


class CatalogSort(str, Enum):
    DEFAULT = "default"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    RATING = "rating"
    SALES = "sales"


async def catalog_page(db, stmt, sort, cutoff, skip, limit):
    """Page paid placements separately so the ordinary catalog keeps its index."""
    async def rows(query, offset, size):
        result = await db.scalars(query.offset(offset).limit(size))
        return list(result.all())

    if sort != CatalogSort.DEFAULT:
        return await rows(apply_catalog_sort(stmt, sort, cutoff), skip, limit)
    from models.promotion import ProductPromotion
    now = datetime.utcnow()
    active = select(ProductPromotion.product_id).where(ProductPromotion.promoted_until > now)
    if await db.scalar(active.limit(1)) is None:
        return await rows(apply_catalog_sort(stmt, sort, promotions=False), skip, limit)
    promoted = stmt.where(Product.id.in_(active))
    count = await db.scalar(select(func.count()).select_from(promoted.subquery()))
    if not count:
        return await rows(apply_catalog_sort(stmt, sort, promotions=False), skip, limit)
    result = []
    if skip < count:
        query = promoted.order_by(func.md5(cast(Product.id, String) + now.strftime("%Y-%m-%d")),
            Product.is_top.desc(), Product.sort_order.desc(), Product.created_at.desc(), Product.id)
        result = await rows(query, skip, limit)
    if len(result) < limit:
        ordinary = apply_catalog_sort(stmt.where(~Product.id.in_(active)), sort, promotions=False)
        result.extend(await rows(ordinary, max(0, skip - count), limit - len(result)))
    return result


def category_filter(category_id):
    # Existing flat categories remain roots. For children this selects only itself.
    return or_(
        Product.category_id == category_id,
        Product.category_id.in_(select(Category.id).where(Category.parent_id == category_id)),
    )


def completed_sale_condition():
    # An order may complete while a seller's item is still in escrow.
    # Require release for any linked deal; never infer settlement from the order alone.
    linked_deal = exists(select(Deal.id).where(Deal.order_item_id == OrderItem.id))
    unsettled_deal = exists(select(Deal.id).where(
        Deal.order_item_id == OrderItem.id, Deal.status != DealStatus.RELEASED,
    ))
    released_deal = exists(select(Deal.id).where(
        Deal.order_item_id == OrderItem.id, Deal.status == DealStatus.RELEASED,
    ))
    return (
        Order.status == OrderStatus.COMPLETED,
        or_(
            ~linked_deal & (func.coalesce(OrderItem.product_snapshot["is_p2p"].as_boolean(), False).is_(False)),
            released_deal & ~unsettled_deal,
        ),
    )


def apply_catalog_sort(stmt, sort: CatalogSort, cutoff: datetime | None = None, promotions: bool = True):
    if sort == CatalogSort.PRICE_ASC:
        return stmt.order_by(Product.price_usdt.asc(), Product.id)
    if sort == CatalogSort.PRICE_DESC:
        return stmt.order_by(Product.price_usdt.desc(), Product.id)
    if sort == CatalogSort.RATING:
        from services.review_service import ranked_seller_reviews, SELLER_REVIEW_LIMIT
        ranked = ranked_seller_reviews()
        seller_ratings = select(ranked.c.seller_user_id, func.avg(Review.rating).label("rating")).join(
            Review, Review.id == ranked.c.review_id,
        ).where(ranked.c.position <= SELLER_REVIEW_LIMIT).group_by(ranked.c.seller_user_id).subquery()
        stmt = stmt.outerjoin(seller_ratings, seller_ratings.c.seller_user_id == Product.owner_user_id)
        rating = select(func.avg(Review.rating)).where(
            Review.product_id == Product.id,
            Review.rating.is_not(None), Review.is_hidden.is_(False),
        )
        value = case((Product.owner_user_id.is_not(None), seller_ratings.c.rating),
                     else_=rating.correlate(Product).scalar_subquery())
        return stmt.order_by(value.desc().nulls_last(), Product.id)
    if sort == CatalogSort.SALES:
        sales = select(func.sum(OrderItem.quantity)).join(Order, Order.id == OrderItem.order_id).where(
            OrderItem.product_id == Product.id, *completed_sale_condition(),
        ).correlate(Product).scalar_subquery()
        return stmt.order_by(func.coalesce(sales, 0).desc(), Product.id)
    if not promotions:
        return stmt.order_by(Product.is_top.desc(), Product.sort_order.desc(), Product.created_at.desc(), Product.id)
    from services.promotion_service import active_promotion_expression
    promoted = active_promotion_expression()
    # A daily deterministic shuffle gives paid placements equal rotation while
    # keeping pagination stable within a catalog browsing session/day.
    shuffle = case((promoted, func.md5(cast(Product.id, String) + datetime.utcnow().strftime("%Y-%m-%d"))), else_="")
    return stmt.order_by(
        promoted.desc(), shuffle, Product.is_top.desc(), Product.sort_order.desc(), Product.created_at.desc(), Product.id,
    )
