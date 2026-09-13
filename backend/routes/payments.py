from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import hashlib
import hmac
import json
import logging
import uuid

from config import settings
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Payments"])


def _verify_cryptobot_signature(raw_body: bytes, received_signature: str | None) -> bool:
    """
    Проверка подлинности вебхука CryptoBot.

    Схема из документации Crypto Pay API:
        secret    = sha256(api_token)
        signature = hmac_sha256(secret, raw_request_body).hexdigest()
    и сравнивается с заголовком crypto-pay-api-signature.

    Раньше проверки не было вовсе (комментарий "aiocryptopay handles this" не
    соответствовал коду) — любой мог отправить сюда чужой order_id и получить
    товар бесплатно.
    """
    if not received_signature:
        return False
    if not settings.CRYPTOBOT_API_TOKEN:
        # Без токена проверить подпись невозможно — считаем запрос неподтверждённым.
        logger.error("[WEBHOOK] CRYPTOBOT_API_TOKEN не задан, проверка подписи невозможна")
        return False

    secret = hashlib.sha256(settings.CRYPTOBOT_API_TOKEN.encode()).digest()
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received_signature)


@router.post("/crypto")
async def cryptobot_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle CryptoBot payment webhook"""
    try:
        raw_body = await request.body()

        if not _verify_cryptobot_signature(
            raw_body, request.headers.get("crypto-pay-api-signature")
        ):
            logger.warning("[WEBHOOK] Отклонён вебхук с неверной подписью")
            raise HTTPException(status_code=401, detail="Invalid signature")

        body = json.loads(raw_body)
        logger.info("[WEBHOOK] Получен подписанный вебхук от CryptoBot")

        update_type = body.get("update_type")
        payload = body.get("payload") or {}
        logger.info("[WEBHOOK] update_type=%s", update_type)

        if update_type == "invoice_paid":
            invoice_id = payload.get("invoice_id")
            order_payload = payload.get("payload")  # Our order_id
            logger.info(
                "[WEBHOOK] Invoice paid — invoice_id=%s order_id=%s", invoice_id, order_payload
            )

            if order_payload:
                # Find order with row locking to prevent race conditions
                stmt = select(Order).where(Order.id == uuid.UUID(order_payload)).with_for_update()
                result = await db.execute(stmt)
                order = result.scalar_one_or_none()

                if order:
                    if order.status.value == "pending":
                        logger.info("[WEBHOOK] Завершаем заказ %s", order.id)
                        # Complete order
                        await complete_order(order, db)

                        # Clear cart for this user after successful payment
                        stmt = select(CartItem).where(CartItem.user_id == order.user_id)
                        result = await db.execute(stmt)
                        cart_items = result.scalars().all()

                        for cart_item in cart_items:
                            await db.delete(cart_item)

                        await db.commit()
                        logger.info("[WEBHOOK] Заказ %s успешно завершён", order.id)
                    else:
                        logger.info(
                            "[WEBHOOK] Заказ %s уже в статусе %s, пропускаем",
                            order.id, order.status.value
                        )
                else:
                    logger.error("[WEBHOOK] Заказ %s не найден", order_payload)
            else:
                logger.error("[WEBHOOK] В вебхуке нет order_payload")
        else:
            logger.info("[WEBHOOK] Игнорируем update_type=%s", update_type)

        return {"status": "ok"}

    except HTTPException:
        # Не заворачивать 401 от проверки подписи в 400
        raise
    except Exception as e:
        logger.exception("[WEBHOOK] Ошибка обработки вебхука: %s", e)
        raise HTTPException(status_code=400, detail="Webhook error")


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
