"""Админка реферальной программы: история начислений и топ рефереров."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.referral import ReferralTransaction
from models.user import User
from utils.auth import require_admin

router = APIRouter(prefix="/api/admin/referrals", tags=["Admin Referrals"])


def _apply_filters(
    stmt: Select,
    *,
    level: Optional[int],
    source: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    referrer_id: Optional[uuid.UUID],
) -> Select:
    if level is not None:
        stmt = stmt.where(ReferralTransaction.level == level)
    if source:
        stmt = stmt.where(ReferralTransaction.source == source)
    if date_from:
        stmt = stmt.where(ReferralTransaction.created_at >= date_from)
    if date_to:
        stmt = stmt.where(ReferralTransaction.created_at <= date_to)
    if referrer_id:
        stmt = stmt.where(ReferralTransaction.referrer_id == referrer_id)
    return stmt


@router.get("")
async def list_accruals(
    level: Optional[int] = Query(None, ge=1, le=2),
    source: Optional[str] = Query(None, pattern="^(product|subscription|p2p)$"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    referrer_id: Optional[uuid.UUID] = None,
    search: Optional[str] = Query(None, max_length=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    История начислений с фильтрами и пагинацией.

    Имена пользователей подтягиваются одним запросом: на каждую строку
    отдельный запрос за реферером и рефералом — это по два лишних обращения
    к базе на запись.
    """
    if search:
        pattern = f"%{search}%"
        matched = (await db.execute(
            select(User.id).where(or_(
                User.username.ilike(pattern),
                User.first_name.ilike(pattern),
            ))
        )).scalars().all()
        # Пустой список даст `IN ()` и корректно вернёт ноль строк
        base_filter = ReferralTransaction.referrer_id.in_(matched)
    else:
        base_filter = None

    stmt = select(ReferralTransaction)
    count_stmt = select(func.count(ReferralTransaction.id))
    if base_filter is not None:
        stmt = stmt.where(base_filter)
        count_stmt = count_stmt.where(base_filter)

    filters = dict(
        level=level, source=source, date_from=date_from,
        date_to=date_to, referrer_id=referrer_id,
    )
    stmt = _apply_filters(stmt, **filters)
    count_stmt = _apply_filters(count_stmt, **filters)

    total = (await db.execute(count_stmt)).scalar() or 0
    rows = (await db.execute(
        stmt.order_by(ReferralTransaction.created_at.desc()).offset(skip).limit(limit)
    )).scalars().all()

    user_ids = {r.referrer_id for r in rows} | {r.referral_id for r in rows}
    users: dict[uuid.UUID, User] = {}
    if user_ids:
        found = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        users = {u.id: u for u in found}

    def describe(user_id: uuid.UUID) -> dict:
        user = users.get(user_id)
        if user is None:
            return {"id": str(user_id), "username": None, "telegram_id": None}
        return {
            "id": str(user.id),
            "username": user.username,
            "telegram_id": user.telegram_id,
        }

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [
            {
                "id": str(r.id),
                "referrer": describe(r.referrer_id),
                "referral": describe(r.referral_id),
                "order_id": str(r.order_id),
                "amount": str(r.amount),
                "currency": r.currency,
                "level": r.level,
                # NULL у начислений до этапа 6 — тогда процент задавался в .env
                # и восстановить его нечем
                "percent_bp_applied": r.percent_bp_applied,
                "source": r.source,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/top")
async def top_referrers(
    limit: int = Query(20, ge=1, le=100),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Кто больше всех заработал на рефералах."""
    stmt = (
        select(
            ReferralTransaction.referrer_id,
            func.sum(ReferralTransaction.amount).label("earned"),
            func.count(ReferralTransaction.id).label("accruals"),
        )
        .group_by(ReferralTransaction.referrer_id)
        .order_by(func.sum(ReferralTransaction.amount).desc())
        .limit(limit)
    )
    if date_from:
        stmt = stmt.where(ReferralTransaction.created_at >= date_from)
    if date_to:
        stmt = stmt.where(ReferralTransaction.created_at <= date_to)

    rows = (await db.execute(stmt)).all()
    if not rows:
        return {"items": []}

    referrer_ids = [r.referrer_id for r in rows]
    users = {
        u.id: u for u in
        (await db.execute(select(User).where(User.id.in_(referrer_ids)))).scalars().all()
    }

    # Число приглашённых — одним запросом с группировкой, а не циклом
    invited_rows = (await db.execute(
        select(User.referrer_id, func.count(User.id))
        .where(User.referrer_id.in_(referrer_ids))
        .group_by(User.referrer_id)
    )).all()
    invited = {row[0]: row[1] for row in invited_rows}

    return {
        "items": [
            {
                "user_id": str(row.referrer_id),
                "username": users[row.referrer_id].username if row.referrer_id in users else None,
                "telegram_id": users[row.referrer_id].telegram_id if row.referrer_id in users else None,
                "earned": str(row.earned),
                "accruals": row.accruals,
                "invited": invited.get(row.referrer_id, 0),
            }
            for row in rows
        ],
    }
