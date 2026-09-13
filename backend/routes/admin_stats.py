from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database import get_db
from models.user import User
from models.order import Order
from models.product import Product
from schemas.auth import TokenResponse
from utils.admin_deps import get_current_admin_user
from datetime import datetime, timedelta
from typing import Literal

router = APIRouter(prefix="/api/admin", tags=["Admin Stats"])

@router.get("/stats")
async def get_stats(
    period: Literal['all', '30d', '7d', '24h'] = 'all',
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    # Total Users (Always cumulative)
    users_query = select(func.count(User.id))
    total_users = (await db.execute(users_query)).scalar() or 0

    # Total Products (Always cumulative)
    products_query = select(func.count(Product.id))
    total_products = (await db.execute(products_query)).scalar() or 0

    # Date Filter for Orders and Revenue
    filter_date = None
    if period == '30d':
        filter_date = datetime.utcnow() - timedelta(days=30)
    elif period == '7d':
        filter_date = datetime.utcnow() - timedelta(days=7)
    elif period == '24h':
        filter_date = datetime.utcnow() - timedelta(hours=24)

    # Orders Query
    orders_query = select(func.count(Order.id))
    if filter_date:
        orders_query = orders_query.where(Order.created_at >= filter_date)
    total_orders = (await db.execute(orders_query)).scalar() or 0

    # Revenue Query (Assuming status 'completed' and summing total_amount_usdt)
    revenue_query = select(func.sum(Order.total_usdt)).where(Order.status == 'completed')
    if filter_date:
        revenue_query = revenue_query.where(Order.created_at >= filter_date)
    total_revenue = (await db.execute(revenue_query)).scalar() or 0.0

    return {
        "total_users": total_users,
        "total_orders": total_orders,
        "total_revenue_usdt": total_revenue,
        "total_products": total_products
    }
