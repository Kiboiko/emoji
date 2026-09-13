from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from database import get_db
from models.user import User
from models.order import Order, OrderStatus, OrderItem
from models.cart import CartItem
from models.product import Product
from models.digital_item import DigitalItem
from schemas.order import OrderCreate, OrderResponse
from utils.auth import get_current_user, require_admin
from services import payment_service, settings_service
from services.telegram_service import telegram_service
from services.referral_service import process_referral_commission
from utils.websockets import manager
from fastapi.encoders import jsonable_encoder
from schemas.product import ProductResponse

logger = logging.getLogger(__name__)

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
    """
    Создаёт ОДИН заказ на всю корзину и выставляет счёт в TON.

    Раньше на каждую позицию корзины создавался отдельный заказ со своим
    инвойсом, а фронт открывал только первый — остальные висели неоплаченными.
    С TON Connect это было бы ещё хуже: каждый заказ требует отдельной подписи
    транзакции в кошельке, то есть корзина из трёх товаров = три подписи.

    Теперь: одна корзина = один заказ = одна транзакция = одна подпись.
    """
    cart_items = (
        await db.execute(select(CartItem).where(CartItem.user_id == user.id))
    ).scalars().all()

    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Резерв держим ровно столько же, сколько живёт счёт: раньше товар
    # резервировался на 3 минуты, а заказ отменялся через 120 — между этими
    # значениями резерв успевал протухнуть на оплаченном заказе.
    reservation_minutes = await settings_service.get_int(db, "order_payment_ttl_min")
    reserved_until = datetime.utcnow() + timedelta(minutes=reservation_minutes)

    order = Order(
        id=uuid.uuid4(),
        user_id=user.id,
        total_usdt=Decimal("0"),
        total_ton=None,
        currency=order_data.currency,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    await db.flush()

    total_usdt = Decimal("0")
    out_of_stock_products: list[str] = []
    updated_products: list[Product] = []

    for cart_item in cart_items:
        product = await db.get(Product, cart_item.product_id)
        if not product:
            continue

        quantity = cart_item.quantity
        item_total = product.price_usdt * quantity
        total_usdt += item_total

        if product.type == "digital":
            await _reserve_digital_items(
                db, order=order, product=product, quantity=quantity,
                reserved_until=reserved_until,
            )
            if product.stock is not None:
                product.stock -= quantity
                db.add(product)
                updated_products.append(product)
                if product.stock == 0:
                    out_of_stock_products.append(product.name_ru)

        db.add(OrderItem(
            id=uuid.uuid4(),
            order_id=order.id,
            product_id=product.id,
            quantity=quantity,
            price_usdt=product.price_usdt,
            price_ton=product.price_ton,
            product_snapshot={
                "name_ru": product.name_ru,
                "name_en": product.name_en,
                "description_ru": product.description_ru,
                "description_en": product.description_en,
                "content_data": product.content_data,
                "type": product.type,
                "image_url": product.image_url,
            },
            user_data=cart_item.user_data,
        ))

    if total_usdt <= 0:
        raise HTTPException(status_code=400, detail="Cart contains no valid products")

    order.total_usdt = total_usdt
    await db.flush()

    payment = await payment_service.create_or_refresh_payment(db, order)
    tx_request = payment_service.build_transaction_request(payment)

    await db.commit()

    # Уведомления и broadcast — после коммита: их падение не должно
    # откатывать уже созданный заказ.
    for product in updated_products:
        await manager.broadcast({
            "type": "product_updated",
            "data": jsonable_encoder(ProductResponse.model_validate(product)),
        })
    for name in out_of_stock_products:
        try:
            await telegram_service.send_out_of_stock_notification(name)
        except Exception as e:
            logger.warning("Не удалось отправить уведомление об окончании товара: %s", e)

    return {
        "order_id": str(order.id),
        "total_usdt": str(total_usdt),
        "payment": tx_request.as_dict(),
    }


async def _reserve_digital_items(
    db: AsyncSession,
    *,
    order: Order,
    product: Product,
    quantity: int,
    reserved_until: datetime,
) -> None:
    """
    Резервирует цифровые товары под заказ.

    SELECT ... FOR UPDATE обязателен: без блокировки двое покупателей в один
    момент получают одни и те же экземпляры.
    """
    now = datetime.utcnow()
    stmt = (
        select(DigitalItem)
        .where(
            DigitalItem.product_id == product.id,
            DigitalItem.is_sold == False,  # noqa: E712
            or_(DigitalItem.order_id == None, DigitalItem.reserved_until < now),  # noqa: E711
        )
        .limit(quantity)
        .with_for_update()
    )
    available = (await db.execute(stmt)).scalars().all()

    if len(available) < quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough stock for product '{product.name_ru}'",
        )

    for item in available:
        item.order_id = order.id
        item.reserved_until = reserved_until
        db.add(item)


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
