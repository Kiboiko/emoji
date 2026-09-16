from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Date
from database import get_db
from models.user import User
from models.order import Order, OrderItem, OrderStatus
from models.product import Product
from models.p2p import Deal, DealStatus, ListingStatus, ProductListing
from models.subscription import Channel, ChannelStatus
from models.withdrawal import Withdrawal, WithdrawalStatus
from schemas.auth import TokenResponse
from utils.admin_deps import get_current_admin_user
from datetime import datetime, timedelta
from typing import Literal

router = APIRouter(prefix="/api/admin", tags=["Admin Stats"])

# Деньги реально получены уже в PAID: COMPLETED наступает позже и не для всех
# заказов — услуги ждут ручной обработки, P2P ждёт подтверждения получения.
# Считая выручку только по COMPLETED, прежняя версия занижала её тем сильнее,
# чем больше на площадке услуг и товаров пользователей.
PAID_STATUSES = [OrderStatus.PAID, OrderStatus.COMPLETED]


def _period_start(period: str) -> datetime | None:
    if period == '30d':
        return datetime.utcnow() - timedelta(days=30)
    if period == '7d':
        return datetime.utcnow() - timedelta(days=7)
    if period == '24h':
        return datetime.utcnow() - timedelta(hours=24)
    return None


@router.get("/stats")
async def get_stats(
    period: Literal['all', '30d', '7d', '24h'] = 'all',
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    total_products = (await db.execute(select(func.count(Product.id)))).scalar() or 0

    filter_date = _period_start(period)

    orders_query = select(func.count(Order.id))
    if filter_date:
        orders_query = orders_query.where(Order.created_at >= filter_date)
    total_orders = (await db.execute(orders_query)).scalar() or 0

    revenue_query = select(func.coalesce(func.sum(Order.total_usdt), 0)).where(
        Order.status.in_(PAID_STATUSES)
    )
    if filter_date:
        revenue_query = revenue_query.where(Order.created_at >= filter_date)
    total_revenue = (await db.execute(revenue_query)).scalar() or 0

    return {
        "total_users": total_users,
        "total_orders": total_orders,
        "total_revenue_usdt": total_revenue,
        "total_products": total_products,
    }


@router.get("/stats/attention")
async def needs_attention(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user),
):
    """
    Счётчики «требует действия администратора».

    Главный экран должен сразу показывать, где люди чего-то ждут: заявка на
    модерации, открытый спор или заявка на вывод — это всегда чьё-то
    ожидание, а не просто цифра.
    """
    async def count(stmt) -> int:
        return (await db.execute(stmt)).scalar() or 0

    return {
        "listings_pending": await count(
            select(func.count(ProductListing.id))
            .where(ProductListing.status == ListingStatus.PENDING)
        ),
        "disputes_open": await count(
            select(func.count(Deal.id)).where(Deal.status == DealStatus.DISPUTED)
        ),
        "withdrawals_pending": await count(
            select(func.count(Withdrawal.id))
            .where(Withdrawal.status == WithdrawalStatus.PENDING)
        ),
        "channels_pending": await count(
            select(func.count(Channel.id))
            .where(Channel.status == ChannelStatus.PENDING)
        ),
        "service_orders_pending": await count(
            select(func.count(func.distinct(OrderItem.order_id)))
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.status == OrderStatus.PAID,
                OrderItem.product_snapshot['type'].astext == 'service',
            )
        ),
    }


@router.get("/stats/timeseries")
async def revenue_timeseries(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user),
):
    """
    Выручка и число заказов по дням.

    Группировка делается базой, а не Python: тянуть все заказы за период в
    память ради суммы по дням — лишний трафик и память на ровном месте.
    """
    since = datetime.utcnow() - timedelta(days=days)
    day = cast(Order.created_at, Date).label("day")

    rows = (await db.execute(
        select(
            day,
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_usdt), 0),
        )
        .where(Order.created_at >= since, Order.status.in_(PAID_STATUSES))
        .group_by(day)
        .order_by(day)
    )).all()

    by_day = {row[0]: (row[1], row[2]) for row in rows}

    # Дни без заказов возвращаем нулями: иначе график «склеивает» пропуски и
    # неделя простоя выглядит как непрерывные продажи
    start = (datetime.utcnow() - timedelta(days=days - 1)).date()
    series = []
    for offset in range(days):
        current = start + timedelta(days=offset)
        orders_count, revenue = by_day.get(current, (0, 0))
        series.append({
            "date": current.isoformat(),
            "orders": orders_count,
            "revenue_usdt": float(revenue),
        })

    return {"days": days, "series": series}


@router.get("/stats/top-products")
async def top_products(
    limit: int = Query(10, ge=1, le=50),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user),
):
    """Самые продаваемые товары за период — по снимкам позиций."""
    since = datetime.utcnow() - timedelta(days=days)
    name = OrderItem.product_snapshot['name_ru'].astext.label("name")

    rows = (await db.execute(
        select(
            name,
            func.sum(OrderItem.quantity).label("sold"),
            func.sum(OrderItem.price_usdt * OrderItem.quantity).label("revenue"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.created_at >= since, Order.status.in_(PAID_STATUSES))
        .group_by(name)
        .order_by(func.sum(OrderItem.price_usdt * OrderItem.quantity).desc())
        .limit(limit)
    )).all()

    return {
        "items": [
            {"name": row.name, "sold": int(row.sold or 0), "revenue_usdt": float(row.revenue or 0)}
            for row in rows
        ]
    }


@router.get("/stats/conversion")
async def conversion(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user),
):
    """
    Доля заказов, доходящих до оплаты.

    Показывает, сколько людей упирается в оплату и уходит: низкая конверсия
    при рабочих платежах обычно означает проблему в кошельке или в курсе, а
    не в товаре.
    """
    since = datetime.utcnow() - timedelta(days=days)

    rows = (await db.execute(
        select(Order.status, func.count(Order.id))
        .where(Order.created_at >= since)
        .group_by(Order.status)
    )).all()

    by_status = {row[0].value if hasattr(row[0], "value") else str(row[0]): row[1] for row in rows}
    total = sum(by_status.values())
    paid = by_status.get("paid", 0) + by_status.get("completed", 0)

    return {
        "days": days,
        "total": total,
        "paid": paid,
        "by_status": by_status,
        "conversion_percent": round(paid / total * 100, 1) if total else 0.0,
    }
