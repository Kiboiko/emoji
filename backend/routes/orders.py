from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
import uuid
from datetime import datetime
from decimal import Decimal

from database import get_db
from models.user import User
from models.order import Order, OrderStatus, OrderItem
from models.cart import CartItem
from models.product import Product
from models.digital_item import DigitalItem
from schemas.order import OrderCreate, OrderResponse
from utils.auth import get_current_user, require_admin
from services.payment_service import cryptobot_service
from services.telegram_service import telegram_service
from services.referral_service import process_referral_commission
from utils.websockets import manager
from fastapi.encoders import jsonable_encoder
from schemas.product import ProductResponse

router = APIRouter(prefix="/api/orders", tags=["Orders"])


@router.get("", response_model=list[OrderResponse])
async def get_user_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's order history"""
    stmt = select(Order).options(
        selectinload(Order.items),
        selectinload(Order.reviews)
    ).where(
        Order.user_id == user.id,
        Order.status.in_([OrderStatus.COMPLETED, OrderStatus.PAID])
    ).order_by(Order.created_at.desc())
    result = await db.execute(stmt)
    orders = result.scalars().all()
    
    # Manually populate is_reviewed flag
    response = []
    for order in orders:
        order_data = OrderResponse.model_validate(order)
        reviewed_product_ids = {r.product_id for r in order.reviews}
        for item in order_data.items:
            item.is_reviewed = item.product_id in reviewed_product_ids
        response.append(order_data)
        
    return response


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get order details"""
    stmt = select(Order).options(
        selectinload(Order.items),
        selectinload(Order.reviews)
    ).where(Order.id == uuid.UUID(order_id))
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")
    
    order_data = OrderResponse.model_validate(order)
    reviewed_product_ids = {r.product_id for r in order.reviews}
    for item in order_data.items:
        item.is_reviewed = item.product_id in reviewed_product_ids
        
    return order_data


@router.post("", response_model=dict)
async def create_order(
    order_data: OrderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create separate orders for each cart item"""
    # Get cart items
    stmt = select(CartItem).where(CartItem.user_id == user.id)
    result = await db.execute(stmt)
    cart_items = result.scalars().all()
    
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")
    
    created_orders = []
    first_invoice_url = None
    
    # Create separate order for EACH cart item
    for cart_item in cart_items:
        product = await db.get(Product, cart_item.product_id)
        if not product:
            continue
        
        # Calculate totals for THIS item's quantity
        item_total_usdt = product.price_usdt * cart_item.quantity
        item_total_ton = (product.price_ton * cart_item.quantity) if product.price_ton else None
        
        # Create order for this single item
        order = Order(
            id=uuid.uuid4(),
            user_id=user.id,
            total_usdt=item_total_usdt,
            total_ton=item_total_ton if item_total_ton and item_total_ton > 0 else None,
            currency=order_data.currency,
            status=OrderStatus.PENDING
        )
        db.add(order)
        await db.flush()  # IMPORTANT: Flush to persist order_id before using it
        
        # Check stock and reserve digital items
        RESERVATION_MINUTES = 3
        
        if product.type == "digital":
            quantity = cart_item.quantity
            # Find available items (not sold, AND (not reserved OR reservation expired))
            current_time = datetime.utcnow()
            print(f"[ORDER] DEBUG: Product {product.id} (Digital), Quantity: {quantity}, Time: {current_time}")
            
            stmt = select(DigitalItem).where(
                DigitalItem.product_id == product.id,
                DigitalItem.is_sold == False,
                or_(
                    DigitalItem.order_id == None,
                    DigitalItem.reserved_until < current_time
                )
            ).limit(quantity).with_for_update() # Lock rows to prevent race conditions
            
            result = await db.execute(stmt)
            available_items = result.scalars().all()
            print(f"[ORDER] DEBUG: Found {len(available_items)} available items")
            
            if len(available_items) < quantity:
                print(f"[ORDER] ERROR: Not enough stock. Needed {quantity}, found {len(available_items)}")
                raise HTTPException(
                    status_code=400, 
                    detail=f"Not enough stock for product '{product.name_ru}'"
                )
                
            # Reserve items
            from datetime import timedelta
            reserved_until = current_time + timedelta(minutes=RESERVATION_MINUTES)
            
            for digital_item in available_items:
                digital_item.order_id = order.id
                digital_item.reserved_until = reserved_until
                db.add(digital_item)
            
            # Decrease product stock immediately
            if product.stock is not None:
                product.stock -= quantity
                db.add(product)
                
                # Broadcast real-time stock update
                await manager.broadcast({
                    "type": "product_updated",
                    "data": jsonable_encoder(ProductResponse.model_validate(product))
                })
                
                # Notify admin if out of stock
                print(f"[ORDER] Product {product.name_ru} stock is now: {product.stock}")
                if product.stock == 0:
                    try:
                        await telegram_service.send_out_of_stock_notification(product.name_ru)
                    except Exception as e:
                        print(f"[ORDER] WARNING: Failed to send out-of-stock notification: {e}")
                
        elif product.type in ["instruction", "service"]:
            # Unlimited stock / Manual processing
            pass
            
        # Create single order item for this product
        order_item = OrderItem(
            id=uuid.uuid4(),
            order_id=order.id,
            product_id=product.id,
            quantity=cart_item.quantity,
            price_usdt=product.price_usdt,
            price_ton=product.price_ton,
            product_snapshot={
                "name_ru": product.name_ru,
                "name_en": product.name_en,
                "description_ru": product.description_ru,
                "description_en": product.description_en,
                "content_data": product.content_data,
                # "description_ru": product.description_ru, # Duplicate removed
                # "description_en": product.description_en, # Duplicate removed
                # "content_data": product.content_data, # Duplicate removed
                "type": product.type,
                "image_url": product.image_url
            },
            user_data=cart_item.user_data  # Pass user_data from cart to order item
        )
        db.add(order_item)
        
        await db.flush()  # Flush to get order.id
        
        # Create CryptoBot invoice for THIS order
        # Always send amount in USD - CryptoBot will convert if currency is TON
        invoice = await cryptobot_service.create_invoice(
            amount=item_total_usdt,  # Always USD amount
            currency=order_data.currency,  # But currency can be USDT or TON
            description=f"Order #{order.id} - {product.name_en}",
            payload=str(order.id)
        )
        
        # Save invoice data
        order.cryptobot_invoice_id = invoice["invoice_id"]
        order.payment_data = invoice
        
        created_orders.append({
            "order_id": str(order.id),
            "product_name": product.name_ru,
            "pay_url": invoice["pay_url"],
            "mini_app_url": invoice.get("mini_app_url"),
            "web_app_url": invoice.get("web_app_url")
        })
        
        # Store first invoice URL to redirect user
        if not first_invoice_url:
            first_invoice_url = invoice.get("mini_app_url") or invoice.get("pay_url")
    
    await db.commit()
    
    # Return first payment URL for redirect
    return {
        "orders_created": len(created_orders),
        "order_id": created_orders[0]["order_id"] if created_orders else None,
        "pay_url": created_orders[0]["pay_url"] if created_orders else None,
        "mini_app_url": created_orders[0]["mini_app_url"] if created_orders else None,
        "web_app_url": created_orders[0]["web_app_url"] if created_orders else None,
        "all_orders": created_orders
    }


async def complete_order(order: Order, db: AsyncSession):
    """Complete order after successful payment"""
    # Update order status
    order.status = OrderStatus.PAID
    order.paid_at = datetime.utcnow()
    
    # Process referral commission
    user = await db.get(User, order.user_id)
    await process_referral_commission(db, order, user)
    
    # Fetch items explicitly to avoid async lazy loading errors
    stmt = select(OrderItem).where(OrderItem.order_id == order.id)
    result = await db.execute(stmt)
    items = result.scalars().all()
    
    # Check if order contains service items
    has_service_items = False
    for item in items:
        if item.product_snapshot.get("type") == "service":
            has_service_items = True
            break
            
    # Finalize Digital Items (Mark as sold, clear reservation)
    stmt = select(DigitalItem).where(DigitalItem.order_id == order.id)
    result = await db.execute(stmt)
    reserved_items = result.scalars().all()
    
    for item in reserved_items:
        item.is_sold = True
        item.reserved_until = None
        db.add(item)

    # Mark as completed ONLY if no service items (digital/instruction are instant)
    if not has_service_items:
        order.status = OrderStatus.COMPLETED
    
    await db.commit()
    
    # Send purchase data to user (non-blocking, if fails order still completed)
    try:
        for order_item in items:
            product_name = order_item.product_snapshot.get("name_ru", "Product")
            product_type = order_item.product_snapshot.get("type", "service")
            content_data = order_item.product_snapshot.get("content_data", {})
            quantity = order_item.quantity
            
            # For digital items, fetch actual purchased items
            digital_items_content = []
            if product_type == "digital":
                stmt = select(DigitalItem).where(
                    DigitalItem.order_id == order.id,
                    DigitalItem.product_id == order_item.product_id
                )
                result = await db.execute(stmt)
                purchased_items = result.scalars().all()
                digital_items_content = [item.content for item in purchased_items]
            
            await telegram_service.send_purchase_data(
                telegram_id=user.telegram_id,
                product_name=product_name,
                product_type=product_type,
                quantity=quantity,
                content_data=content_data,
                digital_items=digital_items_content
            )

            # Notify admin if it's a service order
            if product_type == "service":
                try:
                    user_link = order_item.user_data.get("link", "Не указана") if order_item.user_data else "Не указана"
                    await telegram_service.send_new_service_order_notification(
                        product_name=product_name,
                        user_link=user_link,
                        quantity=quantity
                    )
                except Exception as e:
                    print(f"[ORDER] WARNING: Failed to send admin service notification: {e}")
    except Exception as e:
        print(f"[WEBHOOK] WARNING: Failed to send telegram message: {e}")


@router.get("/admin/all", response_model=list[OrderResponse])
async def get_all_orders(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get all orders (admin only)"""
    stmt = select(Order).options(
        selectinload(Order.items),
        selectinload(Order.reviews)
    ).order_by(Order.created_at.desc())
    result = await db.execute(stmt)
    orders = result.scalars().all()
    
    response = []
    for order in orders:
        order_data = OrderResponse.model_validate(order)
        reviewed_product_ids = {r.product_id for r in order.reviews}
        for item in order_data.items:
            item.is_reviewed = item.product_id in reviewed_product_ids
        response.append(order_data)
        
    return response
