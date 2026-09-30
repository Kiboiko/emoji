"""
Остаток товара продавца и снятие брони с неоплаченного заказа.

Сток товара продавца раньше правили приращениями из семи мест, и каждое
считало по-своему: одобрение и правка количества ставили полное число, не
вычитая проданное; снятие с продажи — ноль; отмена заказа и таймаут просто
прибавляли обратно, в том числе к уже снятому товару. Сток расходился с
жизнью в обе стороны: продавец видел «В продаже», а в каталоге вещи не было,
или после одной продажи в продаже снова оказывались все десять штук.

Теперь остаток выводится из фактов, а не из истории приращений:

    заявленное количество − продано по сделкам − забронировано неоплаченными

У снятого с продажи и не одобренного — ноль.

Бронь при оформлении заказа по-прежнему делается вычитанием под блокировкой
строки (orders.create_order): там конкурируют покупатели, и пересчёт внутри
гонки ничего бы не дал. Все остальные места пересчитывают.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.digital_item import DigitalItem
from models.order import Order, OrderItem, OrderStatus
from models.p2p import Deal, DealStatus, ListingStatus, ProductListing
from models.payment import Payment, PaymentStatus
from models.product import Product

logger = logging.getLogger(__name__)


async def units_sold(db: AsyncSession, product_id: uuid.UUID | None) -> int:
    """
    Сколько единиц товара уже разобрали по сделкам.

    Отменённые и возвращённые сделки не считаются: в первом случае заказ не
    оплатили, во втором вещь осталась у продавца.
    """
    if product_id is None:
        return 0

    # Внешнее соединение и единица по умолчанию: order_item_id у сделки
    # необязательный, и на внутреннем соединении такая сделка просто
    # выпадала бы из счёта — то есть проданная вещь считалась бы свободной.
    return (
        await db.execute(
            select(func.coalesce(func.sum(func.coalesce(OrderItem.quantity, 1)), 0))
            .select_from(Deal)
            .outerjoin(OrderItem, OrderItem.id == Deal.order_item_id)
            .where(
                Deal.product_id == product_id,
                Deal.status.notin_([DealStatus.CANCELLED, DealStatus.REFUNDED]),
            )
        )
    ).scalar() or 0


async def units_reserved(db: AsyncSession, product_id: uuid.UUID | None) -> int:
    """Сколько единиц держат заказы, которые оформили, но ещё не оплатили."""
    if product_id is None:
        return 0

    return (
        await db.execute(
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .select_from(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                OrderItem.product_id == product_id,
                Order.status == OrderStatus.PENDING,
            )
        )
    ).scalar() or 0


async def oldest_reservation(db: AsyncSession, product_id: uuid.UUID | None) -> datetime | None:
    """Когда оформлен самый ранний из неоплаченных заказов на этот товар."""
    if product_id is None:
        return None

    return (
        await db.execute(
            select(func.min(Order.created_at))
            .select_from(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                OrderItem.product_id == product_id,
                Order.status == OrderStatus.PENDING,
            )
        )
    ).scalar()


async def available_units(db: AsyncSession, listing: ProductListing) -> int:
    """Сколько единиц по заявке можно купить прямо сейчас."""
    if listing.status != ListingStatus.APPROVED or listing.product_id is None:
        return 0

    taken = await units_sold(db, listing.product_id)
    held = await units_reserved(db, listing.product_id)
    return max(0, listing.quantity - taken - held)


async def refresh_p2p_stock(db: AsyncSession, product_id: uuid.UUID) -> bool:
    """
    Пересчитывает сток товара продавца по его заявке.

    Сначала сбрасывает в базу несохранённые изменения вызывающего: в проекте
    autoflush выключен, и без этого только что отменённый заказ ещё числился
    бы в брони. Строку товара берёт под блокировку — ту же, что при
    оформлении заказа, — чтобы пересчёт не разошёлся с чужой бронью,
    сделанной в ту же секунду.

    Возвращает False, если пересчитывать не из чего — у товара нет заявки,
    и его остаток ведёт кто-то другой.
    """
    await db.flush()

    product = (
        await db.execute(
            select(Product)
            .where(Product.id == product_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if product is None or not product.is_p2p:
        return False

    listing = (
        await db.execute(select(ProductListing).where(ProductListing.product_id == product_id))
    ).scalars().first()
    if listing is None:
        return False

    product.stock = await available_units(db, listing)
    return True


async def release_order(
    db: AsyncSession,
    order: Order,
    *,
    expire_payments: bool,
) -> list[uuid.UUID]:
    """
    Отменяет неоплаченный заказ и снимает его бронь. Коммитит вызывающий.

    expire_payments гасит счёт сразу. Опоздавший перевод это не теряет:
    поллер смотрит и на просроченные счета до конца окна поиска, а платёж по
    отменённому заказу зачисляется покупателю на баланс.

    Возвращает id товаров, чей остаток изменился, — чтобы разослать витринам.
    """
    order.status = OrderStatus.CANCELLED

    if expire_payments:
        payments = (
            await db.execute(select(Payment).where(Payment.order_id == order.id))
        ).scalars().all()
        for payment in payments:
            if payment.status in (PaymentStatus.PENDING, PaymentStatus.SEEN):
                payment.status = PaymentStatus.EXPIRED

    items = (
        await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalars().all()
    p2p_held: dict[uuid.UUID, int] = {}
    for item in items:
        if item.product_id and (item.product_snapshot or {}).get("is_p2p"):
            p2p_held[item.product_id] = p2p_held.get(item.product_id, 0) + item.quantity

    returned: dict[uuid.UUID, int] = {}
    reserved_digital = (
        await db.execute(select(DigitalItem).where(DigitalItem.order_id == order.id))
    ).scalars().all()
    for digital in reserved_digital:
        digital.order_id = None
        digital.reserved_until = None
        if digital.product_id not in p2p_held:
            returned[digital.product_id] = returned.get(digital.product_id, 0) + 1

    # Товар продавца не прибавляем, а пересчитываем: прибавка к снятому с
    # продажи возвращала его в каталог, а к исправленному количеству —
    # продавала больше, чем есть. Прибавляем, только если пересчитать не из
    # чего — у товара нет заявки.
    for product_id, held in p2p_held.items():
        if not await refresh_p2p_stock(db, product_id):
            returned[product_id] = returned.get(product_id, 0) + held

    for product_id, count in returned.items():
        product = await db.get(Product, product_id)
        if product is not None and product.stock is not None:
            product.stock += count

    return list(set(p2p_held) | set(returned))
