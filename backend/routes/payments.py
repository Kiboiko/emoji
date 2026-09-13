"""
Оплата через TON Connect.

Вебхук CryptoBot удалён вместе с провайдером. У блокчейна вебхука нет,
поэтому статус узнаётся двумя путями: фоновым поллером (services/scheduler.py)
и запросом с фронта «проверь сейчас».

Ни один эндпоинт здесь не принимает от клиента факт оплаты. Клиент может
попросить перепроверить платёж, но подтверждение всегда берётся из блокчейна.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.order import Order, OrderStatus
from models.payment import Payment, PaymentStatus
from models.user import User
from schemas.payment import PaymentStatusResponse
from services import payment_service, ton_service
from utils.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payments"])


async def _get_own_order(db: AsyncSession, order_id: str, user: User) -> Order:
    try:
        oid = uuid.UUID(order_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid order id")

    order = await db.get(Order, oid)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")
    return order


@router.get("/config")
async def payment_config():
    """Параметры TON Connect для фронта."""
    return {
        "network": "testnet" if settings.ton_is_testnet else "mainnet",
        "manifest_url": ton_service.manifest_url(),
        "receiving_address": settings.TON_RECEIVING_ADDRESS or None,
    }


@router.post("/ton/init/{order_id}")
async def init_ton_payment(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Выставляет (или обновляет) счёт по заказу.

    Нужен, когда пользователь вернулся к неоплаченному заказу или когда истёк
    зафиксированный курс — тогда выдаётся новый счёт с актуальным курсом.
    """
    order = await _get_own_order(db, order_id, user)

    try:
        payment = await payment_service.create_or_refresh_payment(db, order)
    except ton_service.TonNotConfigured as e:
        logger.error("[PAY] %s", e)
        raise HTTPException(status_code=503, detail="Payments are not configured")
    except ton_service.RateUnavailable as e:
        logger.error("[PAY] %s", e)
        raise HTTPException(status_code=503, detail="Exchange rate is unavailable")
    except payment_service.PaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    return {
        "order_id": str(order.id),
        "payment": payment_service.build_transaction_request(payment).as_dict(),
    }


@router.get("/check/{order_id}", response_model=PaymentStatusResponse)
async def check_payment_status(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Проверяет оплату заказа.

    Вызывается фронтом, пока пользователь ждёт подтверждения. Проверка идёт
    по блокчейну — никаких данных от клиента о том, что он «уже оплатил», не
    принимается.
    """
    order = await _get_own_order(db, order_id, user)

    if order.status in (OrderStatus.PAID, OrderStatus.COMPLETED):
        return PaymentStatusResponse(status=order.status.value, paid=True)

    payment = (
        await db.execute(
            select(Payment)
            .where(Payment.order_id == order.id)
            .order_by(Payment.created_at.desc())
        )
    ).scalars().first()

    if payment is None:
        return PaymentStatusResponse(status=order.status.value, paid=False)

    try:
        status = await payment_service.verify_payment(db, payment)
    except ton_service.TonError as e:
        # Недоступность индексера не должна выглядеть как «не оплачено»
        logger.error("[PAY] Проверка платежа %s не удалась: %s", payment.id, e)
        raise HTTPException(status_code=503, detail="Payment provider is unavailable")

    return PaymentStatusResponse(
        status=status.value,
        paid=status == PaymentStatus.CONFIRMED,
    )
