import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import String, cast, desc, func, or_, select
from typing import Optional, List

from database import get_db
from models.order import Order, OrderItem, OrderStatus
from models.p2p import Deal
from models.payment import Payment
from models.user import User
from models.product import Product
from services.telegram_service import telegram_service
from utils.admin_deps import get_current_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/orders", tags=["Admin Orders"])


from sqlalchemy.orm import selectinload
import traceback

@router.get("/processing")
async def get_service_orders(
    status: str = 'paid',
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        """
        Get service orders for processing.
        status='paid' returns PAID orders (New).
        status='completed' returns COMPLETED orders.
        """
        # Step 1: Get IDs of orders containing services (manually to avoid complex joins)
        # Filter by user_data presence OR product type 'service'
        check_stmt = select(OrderItem.order_id).where(
            or_(
                OrderItem.user_data.isnot(None),
                OrderItem.product_snapshot['type'].astext == 'service'
            )
        )
        check_result = await db.execute(check_stmt)
        # Get unique IDs
        service_order_ids = list(set(check_result.scalars().all()))
        
        if not service_order_ids:
            return []

        # Step 2: Fetch full orders by IDs with User eagerly loaded
        query = select(Order).options(selectinload(Order.user)).where(
            Order.id.in_(service_order_ids)
        )
    
        if status == 'paid':
            query = query.where(Order.status == OrderStatus.PAID)
        elif status == 'completed':
            query = query.where(Order.status == OrderStatus.COMPLETED)
        
        query = query.order_by(desc(Order.created_at))
        
        result = await db.execute(query)
        orders = result.scalars().all()
        
        orders_data = []
        for order in orders:
            # Re-fetch items
            stmt = select(OrderItem).where(OrderItem.order_id == order.id)
            items_res = await db.execute(stmt)
            items = items_res.scalars().all()
            
            # Filter only service items
            service_items = []
            for item in items:
                # Include item if it has user_data OR if it's a service/instruction type
                # This ensures we show the order even if user_data was lost/empty
                is_service = item.product_snapshot.get("type") in ["service", "instruction"]
                if item.user_data or is_service:
                    service_items.append({
                        "id": str(item.id),
                        "product_name": item.product_snapshot.get("name_ru", "Unknown"),
                        "quantity": item.quantity,
                        "user_data": item.user_data or {}, # Ensure not None for frontend
                        "price_usdt": float(item.price_usdt)
                    })
            
            if not service_items:
                continue
    
            orders_data.append({
                "id": str(order.id),
                "user_id": str(order.user_id),
                "user_telegram_id": order.user.telegram_id if order.user else None,
                "user_username": order.user.username if order.user else None,
                "user_first_name": order.user.first_name if order.user else "Unknown",
                "total_usdt": float(order.total_usdt),
                "status": order.status.value,
                "created_at": order.created_at.isoformat(),
                "items": service_items
            })
            
        return orders_data
    except Exception as e:
        print(f"ERROR in get_service_orders: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


@router.post("/{order_id}/complete")
async def complete_service_order(
    order_id: str,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark a service order as completed and notify user"""
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if order.status != OrderStatus.PAID:
        raise HTTPException(status_code=400, detail="Order must be PAID to complete it")
        
    # Update status
    order.status = OrderStatus.COMPLETED
    await db.commit()
    
    # Get order items for notification
    result = await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    items = result.scalars().all()
    
    # Notify user
    user = await db.get(User, order.user_id)
    if user and user.telegram_id:
        try:
            # Construct notification details
            for item in items:
                if item.user_data: # Notification only for service items
                    product_name = item.product_snapshot.get("name_ru", "Unknown")
                    user_link = item.user_data.get("link", "Не указана")
                    quantity = item.quantity
                    
                    await telegram_service.send_service_completion_notification(
                        chat_id=user.telegram_id,
                        order_id=str(order.id),
                        product_name=product_name,
                        user_link=user_link,
                        quantity=quantity
                    )
        except Exception as e:
            print(f"Failed to send notification: {e}")
            
    return {"status": "success", "order_id": str(order.id)}


def _order_filters(
    query,
    *,
    status: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    matched_user_ids: Optional[list],
):
    if status and status != 'all':
        # "paid" показывает и PAID, и COMPLETED: услуги и P2P остаются в PAID
        # до ручной обработки или подтверждения получения, и без COMPLETED
        # список выглядел бы полупустым
        if status == 'paid':
            query = query.where(Order.status.in_(['paid', 'completed']))
        else:
            query = query.where(Order.status == status)
    if date_from:
        query = query.where(Order.created_at >= date_from)
    if date_to:
        query = query.where(Order.created_at <= date_to)
    if matched_user_ids is not None:
        query = query.where(Order.user_id.in_(matched_user_ids))
    return query


@router.get("")
async def get_orders(
    status: Optional[str] = 'paid',
    search: Optional[str] = Query(None, max_length=100),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Список заказов с фильтрами и пагинацией.

    Прежняя версия отдавала все заказы разом и на каждый делала отдельный
    запрос за позициями и ещё один за пользователем: на тысяче заказов это
    две тысячи лишних обращений к базе. Теперь позиции и пользователи
    забираются двумя запросами на страницу.
    """
    matched_user_ids = None
    if search:
        pattern = f"%{search}%"
        matched_user_ids = (await db.execute(
            select(User.id).where(or_(
                User.username.ilike(pattern),
                User.first_name.ilike(pattern),
                cast(User.telegram_id, String).ilike(pattern),
            ))
        )).scalars().all()

    filters = dict(
        status=status, date_from=date_from, date_to=date_to,
        matched_user_ids=matched_user_ids,
    )
    query = _order_filters(select(Order), **filters)
    count_query = _order_filters(select(func.count(Order.id)), **filters)

    total = (await db.execute(count_query)).scalar() or 0
    orders = (await db.execute(
        query.order_by(Order.created_at.desc()).offset(skip).limit(limit)
    )).scalars().all()

    if not orders:
        return {"total": total, "skip": skip, "limit": limit, "items": []}

    order_ids = [o.id for o in orders]
    items = (await db.execute(
        select(OrderItem).where(OrderItem.order_id.in_(order_ids))
    )).scalars().all()
    items_by_order: dict = {}
    for item in items:
        items_by_order.setdefault(item.order_id, []).append(item)

    users = {
        u.id: u for u in (await db.execute(
            select(User).where(User.id.in_({o.user_id for o in orders}))
        )).scalars().all()
    }

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [
            {
                "id": str(order.id),
                "user_id": str(order.user_id),
                "user_telegram_id": users[order.user_id].telegram_id if order.user_id in users else None,
                "user_name": users[order.user_id].first_name if order.user_id in users else "Unknown",
                "user_username": users[order.user_id].username if order.user_id in users else None,
                "total_usdt": float(order.total_usdt),
                "total_ton": float(order.total_ton) if order.total_ton else None,
                "currency": order.currency.value,
                "status": order.status.value,
                "created_at": order.created_at.isoformat(),
                "paid_at": order.paid_at.isoformat() if order.paid_at else None,
                "items": [
                    {
                        "product_name": item.product_snapshot.get("name_ru", "Unknown"),
                        "quantity": item.quantity,
                        "price_usdt": float(item.price_usdt),
                        "is_p2p": bool(item.product_snapshot.get("is_p2p")),
                        "type": item.product_snapshot.get("type"),
                    }
                    for item in items_by_order.get(order.id, [])
                ]
            }
            for order in orders
        ],
    }


@router.get("/{order_id}")
async def order_card(
    order_id: uuid.UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Карточка заказа: состав, покупатель, платёж, сделки."""
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    user = await db.get(User, order.user_id)
    items = (await db.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()

    payment = (await db.execute(
        select(Payment).where(Payment.order_id == order.id)
        .order_by(Payment.created_at.desc())
    )).scalars().first()

    deals = (await db.execute(
        select(Deal).where(Deal.order_id == order.id)
    )).scalars().all()

    return {
        "id": str(order.id),
        "status": order.status.value,
        "currency": order.currency.value,
        "total_usdt": float(order.total_usdt),
        "total_ton": float(order.total_ton) if order.total_ton else None,
        "created_at": order.created_at.isoformat(),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "user": None if user is None else {
            "id": str(user.id),
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
        },
        "payment": None if payment is None else {
            "status": payment.status.value,
            "amount_nano": str(payment.amount_nano or 0),
            "received_nano": str(payment.received_nano or 0),
            "comment": payment.payment_comment,
            "destination_address": payment.destination_address,
            "tx_hash": payment.tx_hash,
            "expires_at": payment.expires_at.isoformat() if payment.expires_at else None,
        },
        "items": [
            {
                "id": str(item.id),
                "product_name": item.product_snapshot.get("name_ru", "Unknown"),
                "type": item.product_snapshot.get("type"),
                "is_p2p": bool(item.product_snapshot.get("is_p2p")),
                "quantity": item.quantity,
                "price_usdt": float(item.price_usdt),
                "user_data": item.user_data or {},
            }
            for item in items
        ],
        "deals": [
            {
                "id": str(d.id),
                "number": d.number,
                "status": d.status.value,
                "product_name": d.product_name,
            }
            for d in deals
        ],
    }


class StatusChange(BaseModel):
    status: OrderStatus
    reason: Optional[str] = Field(None, max_length=500)


@router.post("/{order_id}/status")
async def change_order_status(
    order_id: uuid.UUID,
    payload: StatusChange,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Ручная смена статуса заказа.

    Только статус: денежные последствия отсюда не запускаются. Пометить заказ
    оплаченным вручную нельзя было бы безопасно — деньги в журнал не попадут,
    товар не выдастся, а баланс разойдётся с реальностью. Для возвратов есть
    разбор спора, для выдачи услуги — кнопка «выполнено».
    """
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    if payload.status == OrderStatus.PAID and order.status != OrderStatus.PAID:
        raise HTTPException(
            status_code=400,
            detail="Отметить заказ оплаченным вручную нельзя: оплату "
                   "подтверждает блокчейн. Используйте сверку платежей.",
        )

    previous = order.status
    order.status = payload.status
    await db.commit()

    logger.info(
        "[ADMIN] Заказ %s: статус %s -> %s (админ %s, причина: %s)",
        order.id, previous.value, order.status.value, admin.id, payload.reason or "—",
    )
    return {"id": str(order.id), "status": order.status.value, "previous": previous.value}
