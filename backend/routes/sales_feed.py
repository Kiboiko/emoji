"""Public sales history with an explicit allow-list of non-personal fields."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.order import Order, OrderItem
from models.p2p import Deal, DealStatus, SellerProfile
from models.product import Product
from services.catalog_service import category_filter, completed_sale_condition

router = APIRouter(prefix="/api/sales-feed", tags=["Sales feed"])
FEED_RETENTION = timedelta(days=14)


class SaleItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    product_id: uuid.UUID | None
    name: str
    image_url: str | None
    quantity: int
    total_usd: Decimal
    store_name: str | None
    store_slug: str | None
    completed_at: datetime


class SalesFeed(BaseModel):
    items: list[SaleItem]
    has_more: bool


async def _stores(db, rows):
    # Ownership is only used internally; never expose user UUIDs or order snapshots.
    owner_ids = set()
    for item, _, _ in rows:
        value = (item.product_snapshot or {}).get("owner_user_id")
        try:
            if value:
                owner_ids.add(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError):
            pass
    sellers = (await db.execute(select(SellerProfile).where(
        SellerProfile.user_id.in_(owner_ids),
    ))).scalars().all() if owner_ids else []
    platform = (await db.execute(select(SellerProfile).where(
        SellerProfile.is_platform.is_(True),
    ))).scalars().first()
    return {str(s.user_id): s for s in sellers}, platform


@router.get("", response_model=SalesFeed)
async def get_sales_feed(
    category_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 40,
    lang: str = "ru",
    db: AsyncSession = Depends(get_db),
):
    skip, limit = max(0, skip), max(1, min(limit, 100))
    released_at = select(func.max(Deal.released_at)).where(
        Deal.order_item_id == OrderItem.id, Deal.status == DealStatus.RELEASED,
    ).correlate(OrderItem).scalar_subquery()
    # Legacy orders have no completion timestamp; paid_at is the available event.
    completed_at = func.coalesce(released_at, Order.paid_at, Order.created_at)
    now = datetime.utcnow()
    # The feed is a projection of financial history, not a separate event table.
    # Expire public visibility without deleting orders, settlements or ledger data.
    stmt = select(OrderItem, Order, completed_at.label("completed_at")).join(
        Order, Order.id == OrderItem.order_id,
    ).where(
        *completed_sale_condition(),
        completed_at > now - FEED_RETENTION,
        completed_at <= now,
    )
    if category_id is not None:
        stmt = stmt.join(Product, Product.id == OrderItem.product_id).where(category_filter(category_id))
    rows = (await db.execute(stmt.order_by(
        completed_at.desc(), OrderItem.id,
    ).offset(skip).limit(limit + 1))).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    sellers, platform = await _stores(db, rows)
    items = []
    for item, order, completed in rows:
        snapshot = item.product_snapshot or {}
        owner = snapshot.get("owner_user_id")
        store = sellers.get(owner) if owner else platform
        # Missing sellers stay unknown rather than attributing their sales to the platform.
        items.append(SaleItem(
            id=item.id, product_id=item.product_id,
            name=snapshot.get("name_ru" if lang == "ru" else "name_en") or snapshot.get("name_ru") or "Product",
            image_url=snapshot.get("image_url"),
            quantity=item.quantity, total_usd=item.price_usdt * item.quantity,
            store_name=store.display_name if store else None,
            store_slug=f"seller/{store.id}" if store else None,
            completed_at=completed.replace(tzinfo=timezone.utc),
        ))
    return SalesFeed(items=items, has_more=has_more)
