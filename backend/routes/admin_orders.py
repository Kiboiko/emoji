from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, or_
from typing import Optional, List

from database import get_db
from models.order import Order, OrderItem, OrderStatus
from models.user import User
from models.product import Product
from services.telegram_service import telegram_service
from utils.admin_deps import get_current_admin_user

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


@router.get("")
async def get_orders(
    status: Optional[str] = 'paid',  # Default to paid orders
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all orders for admin - defaults to paid orders only"""
    query = select(Order).join(User, Order.user_id == User.id)
    
    if status and status != 'all':
        # "paid" filter shows both PAID and COMPLETED orders for general view
        if status == 'paid':
            query = query.where(Order.status.in_(['paid', 'completed']))
        else:
            query = query.where(Order.status == status)
    
    query = query.order_by(Order.created_at.desc())
    
    result = await db.execute(query)
    orders = result.scalars().all()
    
    orders_data = []
    for order in orders:
        # Get order items
        stmt = select(OrderItem).where(OrderItem.order_id == order.id)
        items_result = await db.execute(stmt)
        items = items_result.scalars().all()
        
        # Get user
        user = await db.get(User, order.user_id)
        
        orders_data.append({
            "id": str(order.id),
            "user_id": str(order.user_id),
            "user_telegram_id": user.telegram_id if user else None,
            "user_name": user.first_name if user else "Unknown",
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
                    "price_usdt": float(item.price_usdt)
                }
                for item in items
            ]
        })
    
    return orders_data
