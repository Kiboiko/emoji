"""
Отзывы о продавцах: окно давности и рейтинг по нему.

Репутация магазина — это то, как он работает сейчас. Отзыв полугодовой
давности о продавце, который с тех пор сменил подход, покупателю не помощник,
а честному продавцу с одним удачным месяцем даёт вечную фору. Поэтому отзывы о
товарах продавцов (P2P) учитываются и показываются только за последние
seller_reviews_window_days дней (по умолчанию 30; 0 — без ограничения).

Отзывы в базе не удаляются: они остаются в админке и в канале отзывов, а окно
лишь решает, что видит покупатель и что идёт в среднюю оценку. Отзывы на
товары самой площадки и каналов под окно не попадают — это не отзывы о продавце.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.product import Product
from models.review import Review
from services import settings_service


async def window_cutoff(db: AsyncSession) -> datetime | None:
    """Начало окна: отзывы старше не показываются. None — окна нет."""
    days = await settings_service.get_int(db, "seller_reviews_window_days")
    if days <= 0:
        return None
    return datetime.utcnow() - timedelta(days=days)


async def seller_ratings(
    db: AsyncSession, seller_user_ids: list[uuid.UUID],
) -> dict[uuid.UUID, tuple[float | None, int]]:
    """
    Оценка и число отзывов за окно — сразу для многих продавцов одним запросом.

    Ключ — user_id продавца. Продавца без отзывов в словаре нет: вызывающий
    подставляет (None, 0).
    """
    if not seller_user_ids:
        return {}

    stmt = (
        select(Product.owner_user_id, func.avg(Review.rating), func.count(Review.id))
        .join(Product, Product.id == Review.product_id)
        .where(
            Product.owner_user_id.in_(seller_user_ids),
            Review.rating.is_not(None),
            Review.is_hidden.is_(False),
        )
        .group_by(Product.owner_user_id)
    )
    cutoff = await window_cutoff(db)
    if cutoff is not None:
        stmt = stmt.where(Review.created_at >= cutoff)

    return {
        user_id: (round(float(average), 2), int(count))
        for user_id, average, count in (await db.execute(stmt)).all()
    }


async def seller_rating(
    db: AsyncSession, seller_user_id: uuid.UUID | None,
) -> tuple[float | None, int]:
    """Оценка одного продавца за окно: (среднее или None, число отзывов)."""
    if seller_user_id is None:
        return None, 0
    return (await seller_ratings(db, [seller_user_id])).get(seller_user_id, (None, 0))
