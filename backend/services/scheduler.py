import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging

from config import settings
from database import AsyncSessionLocal
from models.order import Order, OrderStatus
from models.digital_item import DigitalItem
from models.product import Product

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

from utils.websockets import manager
from schemas.product import ProductResponse
from fastapi.encoders import jsonable_encoder

async def cleanup_reservations():
    """
    Отменяет неоплаченные заказы и освобождает зарезервированные товары.

    Срок берётся из настройки order_payment_ttl_min, а не зашит в код: раньше
    здесь стояли жёсткие 120 минут, при том что резерв цифровых товаров жил
    3 минуты. Между этими значениями резерв успевал протухнуть на ещё живом
    заказе, и товар мог уйти другому покупателю.

    Небольшой запас сверх срока даётся намеренно: платёж мог уйти в сеть
    в последнюю секунду и подтвердиться чуть позже.
    """
    from services import settings_service

    async with AsyncSessionLocal() as db:
        try:
            ttl_minutes = await settings_service.get_int(db, "order_payment_ttl_min")
            grace = timedelta(seconds=settings.TON_LOOKAHEAD_SECONDS)
            expiration_time = datetime.utcnow() - timedelta(minutes=ttl_minutes) - grace

            stmt = select(Order).where(
                Order.status == OrderStatus.PENDING,
                Order.created_at < expiration_time
            )
            result = await db.execute(stmt)
            expired_orders = result.scalars().all()
            
            if not expired_orders:
                return

            logger.info(f"[SCHEDULER] Found {len(expired_orders)} expired orders")
            
            for order in expired_orders:
                logger.info(f"[SCHEDULER] Cancelling order {order.id}")
                
                # 2. Update Order Status
                order.status = OrderStatus.CANCELLED
                
                # 3. Release Digital Items linked to this order
                stmt_items = select(DigitalItem).where(DigitalItem.order_id == order.id)
                result_items = await db.execute(stmt_items)
                reserved_items = result_items.scalars().all()
                
                # Group by product to restore stock efficiently
                product_counts = {}
                
                for item in reserved_items:
                    item.order_id = None
                    item.reserved_until = None
                    db.add(item)
                    
                    # Count for stock restoration
                    product_counts[item.product_id] = product_counts.get(item.product_id, 0) + 1
                    
                # 4. Restore Product Stock
                for product_id, count in product_counts.items():
                    product = await db.get(Product, product_id)
                    if product and product.stock is not None:
                        product.stock += count
                        db.add(product)
                        logger.info(f"[SCHEDULER] Restored {count} stock for product {product.id}")
                        
                        # Broadcast update
                        await manager.broadcast({
                            "type": "product_updated",
                            "data": jsonable_encoder(ProductResponse.model_validate(product))
                        })
                        
            await db.commit()
            
        except Exception as e:
            logger.error(f"[SCHEDULER] Error in cleanup_reservations: {e}")
            await db.rollback()

async def reconcile_finances():
    """
    Ежедневная сверка финансов: балансы против журнала и глобальный ноль.

    Расхождение означает, что деньги двигали в обход финансового слоя, и это
    надо увидеть сразу, а не при разборе жалобы через месяц. Поэтому при
    несходе шлём алерт админу в Telegram.
    """
    from services import finance_service
    from services.telegram_service import telegram_service

    async with AsyncSessionLocal() as db:
        try:
            report = await finance_service.reconcile(db)
        except Exception as e:
            logger.exception("[SCHEDULER] Сверка упала: %s", e)
            return

        if report.ok:
            return

        lines = [
            "СВЕРКА ФИНАНСОВ НЕ СОШЛАСЬ",
            f"Проверено счетов: {report.checked_accounts}",
            f"Расхождений: {len(report.issues)}",
            f"Суммы по валютам (должны быть 0): {report.global_sum_by_currency}",
        ]
        lines += [f"  {issue}" for issue in report.issues[:10]]
        if len(report.issues) > 10:
            lines.append(f"  ... и ещё {len(report.issues) - 10}")

        for chat_id in telegram_service.admin_chat_ids:
            try:
                await telegram_service.send_message(chat_id, "\n".join(lines), parse_mode=None)
            except Exception as e:
                logger.error("[SCHEDULER] Не удалось отправить алерт сверки в %s: %s", chat_id, e)


async def auto_confirm_deals():
    """
    Автоподтверждение P2P-сделок с истёкшим сроком.

    Раз в час. Без неё деньги продавца зависали бы навсегда, если покупатель
    получил товар и просто не нажал кнопку.
    """
    from services import deal_service

    async with AsyncSessionLocal() as db:
        try:
            await deal_service.auto_confirm_due_deals(db)
        except Exception as e:
            logger.exception("[SCHEDULER] Автоподтверждение сделок упало: %s", e)
            await db.rollback()


async def poll_ton_payments():
    """
    Опрос блокчейна по ожидающим платежам.

    Интервал 15 секунд — компромисс между отзывчивостью (пользователь ждёт
    товар) и лимитами индексера. Все ожидающие платежи проверяются ОДНИМ
    запросом к индексеру, поэтому нагрузка не растёт с числом заказов.
    """
    from services import payment_service

    async with AsyncSessionLocal() as db:
        try:
            await payment_service.poll_pending_payments(db)
        except Exception as e:
            logger.exception("[SCHEDULER] Опрос платежей упал: %s", e)
            await db.rollback()


async def process_subscriptions():
    """
    Истечение подписок и напоминания.

    Раз в час, а не чаще: доступ в канал не требует посекундной точности, а
    каждый прогон — это вызовы Telegram API по каждой истёкшей подписке.
    """
    from services import subscription_service

    async with AsyncSessionLocal() as db:
        try:
            await subscription_service.expire_due_subscriptions(db)
            await subscription_service.send_expiry_reminders(db)
        except Exception as e:
            logger.exception("[SCHEDULER] Обработка подписок упала: %s", e)
            await db.rollback()


def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(
            cleanup_reservations,
            trigger=IntervalTrigger(seconds=300), # Run every 5 minutes
            id="cleanup_reservations",
            replace_existing=True
        )
        scheduler.add_job(
            poll_ton_payments,
            trigger=IntervalTrigger(seconds=15),
            id="poll_ton_payments",
            replace_existing=True
        )
        scheduler.add_job(
            auto_confirm_deals,
            trigger=IntervalTrigger(hours=1),
            id="auto_confirm_deals",
            replace_existing=True
        )
        scheduler.add_job(
            process_subscriptions,
            trigger=IntervalTrigger(hours=1),
            id="process_subscriptions",
            replace_existing=True
        )
        scheduler.add_job(
            reconcile_finances,
            trigger=IntervalTrigger(hours=24),
            id="reconcile_finances",
            replace_existing=True
        )
        scheduler.start()
        logger.info("[SCHEDULER] Started background tasks")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
