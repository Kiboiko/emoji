from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from database import get_db
from models.user import User
from models.order import Order
from models.cart import CartItem
from schemas.payment import PaymentStatusResponse
from utils.auth import get_current_user
from models.digital_item import DigitalItem
from routes.orders import complete_order

# Removed local wrapper as logic is now in routes/orders.py
from services.payment_service import cryptobot_service

router = APIRouter(prefix="/webhook", tags=["Payments"])


@router.post("/crypto")
async def cryptobot_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle CryptoBot payment webhook"""
    try:
        body = await request.json()
        print(f"[WEBHOOK] Received webhook from CryptoBot: {body}")
        
        # Verify webhook (aiocryptopay handles this)
        update_type = body.get("update_type")
        payload = body.get("payload")
        print(f"[WEBHOOK] update_type: {update_type}, payload: {payload}")
        
        if update_type == "invoice_paid":
            invoice_id = payload.get("invoice_id")
            order_payload = payload.get("payload")  # Our order_id
            print(f"[WEBHOOK] Invoice paid - invoice_id: {invoice_id}, order_id: {order_payload}")
            
            if order_payload:
                # Find order with row locking to prevent race conditions
                stmt = select(Order).where(Order.id == uuid.UUID(order_payload)).with_for_update()
                result = await db.execute(stmt)
                order = result.scalar_one_or_none()
                
                if order:
                    print(f"[WEBHOOK] Order found: {order.id}, status={order.status.value}")
                    if order.status.value == "pending":
                        print(f"[WEBHOOK] Completing order {order.id}")
                        # Complete order
                        await complete_order(order, db)
                        
                        # Clear cart for this user after successful payment
                        stmt = select(CartItem).where(CartItem.user_id == order.user_id)
                        result = await db.execute(stmt)
                        cart_items = result.scalars().all()
                        print(f"[WEBHOOK] Clearing {len(cart_items)} cart items")
                        
                        for cart_item in cart_items:
                            await db.delete(cart_item)
                        
                        await db.commit()
                        print(f"[WEBHOOK] Order {order.id} completed successfully")
                    else:
                        print(f"[WEBHOOK] Order already in status {order.status.value}, skipping")
                else:
                    print(f"[WEBHOOK] ERROR: Order {order_payload} not found!")
            else:
                print(f"[WEBHOOK] ERROR: No order_payload in webhook!")
        else:
            print(f"[WEBHOOK] Ignoring update_type: {update_type}")
        
        return {"status": "ok"}
    
    except Exception as e:
        print(f"[WEBHOOK] ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"Webhook error: {str(e)}")


@router.get("/check/{order_id}", response_model=PaymentStatusResponse)
async def check_payment_status(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Check payment status for an order"""
    order = await db.get(Order, uuid.UUID(order_id))
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # If already paid, return status
    if order.status.value in ["paid", "completed"]:
        return PaymentStatusResponse(
            status=order.status.value,
            paid=True
        )
    
    # Check with CryptoBot
    if order.cryptobot_invoice_id:
        try:
            invoice_status = await cryptobot_service.get_invoice_status(
                int(order.cryptobot_invoice_id)
            )
            
            # If paid, complete order
            if invoice_status["paid"]:
                await complete_order(order, db)
                return PaymentStatusResponse(
                    status="paid",
                    paid=True
                )
            
            return PaymentStatusResponse(
                status=invoice_status["status"],
                paid=False
            )
        
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to check status: {str(e)}")
    
    return PaymentStatusResponse(
        status=order.status.value,
        paid=False
    )
