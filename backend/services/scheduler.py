import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging

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
    Check for pending orders created more than 120 minutes ago.
    Cancel them, release digital items, and restore stock.
    """
    async with AsyncSessionLocal() as db:
        try:
            # 1. Find expired pending orders
            expiration_time = datetime.utcnow() - timedelta(minutes=120)
            
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

def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(
            cleanup_reservations,
            trigger=IntervalTrigger(seconds=300), # Run every 5 minutes
            id="cleanup_reservations",
            replace_existing=True
        )
        scheduler.start()
        logger.info("[SCHEDULER] Started background tasks")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
