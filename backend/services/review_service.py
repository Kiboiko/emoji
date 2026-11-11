"""
Последние 50 видимых отзывов продавца во всех его товарах и средняя оценка
по этому же набору. Старые записи доступны администратору.
window_cutoff сохранён для чтения прежней настройки и исторических callers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.product import Product
from models.review import Review
from services import settings_service

SELLER_REVIEW_LIMIT = 50


def ranked_seller_reviews(seller_user_ids=None):
    """Rank visible reviews across every product belonging to each seller."""
    stmt = select(
        Review.id.label("review_id"), Product.owner_user_id.label("seller_user_id"),
        func.row_number().over(partition_by=Product.owner_user_id,
            order_by=(Review.created_at.desc(), Review.id.desc())).label("position"),
    ).join(Product, Product.id == Review.product_id).where(
        Product.owner_user_id.is_not(None), Review.is_hidden.is_(False),
    )
    if seller_user_ids is not None:
        stmt = stmt.where(Product.owner_user_id.in_(seller_user_ids))
    return stmt.subquery()


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
    Оценка и число последних 50 отзывов для многих продавцов одним запросом.

    Ключ — user_id продавца. Продавца без отзывов в словаре нет: вызывающий
    подставляет (None, 0).
    """
    if not seller_user_ids:
        return {}

    ranked = ranked_seller_reviews(seller_user_ids)
    stmt = select(ranked.c.seller_user_id, func.avg(Review.rating), func.count(Review.id)).join(
        Review, Review.id == ranked.c.review_id,
    ).where(ranked.c.position <= SELLER_REVIEW_LIMIT).group_by(ranked.c.seller_user_id)

    return {
        user_id: (round(float(average), 2) if average is not None else None, int(count))
        for user_id, average, count in (await db.execute(stmt)).all()
    }


async def seller_rating(
    db: AsyncSession, seller_user_id: uuid.UUID | None,
) -> tuple[float | None, int]:
    """Оценка одного продавца за окно: (среднее или None, число отзывов)."""
    if seller_user_id is None:
        return None, 0
    return (await seller_ratings(db, [seller_user_id])).get(seller_user_id, (None, 0))
