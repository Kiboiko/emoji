"""
Админка: пользователи.

Заменяет прежний GET /api/users/admin/all, который отдавал всю таблицу разом,
без поиска и без пагинации.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.finance import Account, AccountOwnerType
from models.order import Order, OrderStatus
from models.p2p import Deal, DealStatus, SellerProfile
from models.referral import ReferralTransaction
from models.user import User
from models.withdrawal import Withdrawal
from services.money import from_minor
from utils.admin_deps import get_current_admin_user

router = APIRouter(prefix="/api/admin/users", tags=["Admin Users"])

SortField = Literal["created_at", "referral_earnings", "telegram_id"]


class BlockRequest(BaseModel):
    blocked: bool
    reason: Optional[str] = Field(None, max_length=500)


def _search_filter(stmt: Select, search: str) -> Select:
    """
    Поиск по имени, username и telegram_id.

    Числовой ввод трактуется и как telegram_id, и как подстрока: администратор
    обычно копирует полный ID, но может искать и по хвосту.
    """
    pattern = f"%{search}%"
    conditions = [
        User.username.ilike(pattern),
        User.first_name.ilike(pattern),
        cast(User.telegram_id, String).ilike(pattern),
    ]
    return stmt.where(or_(*conditions))


@router.get("")
async def list_users(
    search: Optional[str] = Query(None, max_length=100),
    blocked: Optional[bool] = None,
    sort: SortField = "created_at",
    order: Literal["asc", "desc"] = "desc",
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Список пользователей с поиском, фильтром и пагинацией."""
    stmt = select(User)
    count_stmt = select(func.count(User.id))

    if search:
        stmt = _search_filter(stmt, search)
        count_stmt = _search_filter(count_stmt, search)
    if blocked is not None:
        stmt = stmt.where(User.is_blocked == blocked)
        count_stmt = count_stmt.where(User.is_blocked == blocked)

    total = (await db.execute(count_stmt)).scalar() or 0

    sort_column = getattr(User, sort)
    stmt = stmt.order_by(
        sort_column.asc() if order == "asc" else sort_column.desc()
    ).offset(skip).limit(limit)

    users = (await db.execute(stmt)).scalars().all()
    if not users:
        return {"total": total, "skip": skip, "limit": limit, "items": []}

    user_ids = [u.id for u in users]

    # Счётчики и суммы — агрегатами с группировкой. По запросу на пользователя
    # получилось бы 3 обращения к базе на каждую строку списка.
    order_rows = (await db.execute(
        select(
            Order.user_id,
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_usdt), 0),
        )
        .where(
            Order.user_id.in_(user_ids),
            Order.status.in_([OrderStatus.PAID, OrderStatus.COMPLETED]),
        )
        .group_by(Order.user_id)
    )).all()
    orders_by_user = {row[0]: (row[1], row[2]) for row in order_rows}

    referral_rows = (await db.execute(
        select(User.referrer_id, func.count(User.id))
        .where(User.referrer_id.in_(user_ids))
        .group_by(User.referrer_id)
    )).all()
    referrals_by_user = {row[0]: row[1] for row in referral_rows}

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [
            {
                "id": str(u.id),
                "telegram_id": u.telegram_id,
                "username": u.username,
                "first_name": u.first_name,
                "is_admin": u.is_admin,
                "is_blocked": u.is_blocked,
                "referral_code": u.referral_code,
                "referral_earnings": u.referral_earnings,
                "orders_count": orders_by_user.get(u.id, (0, 0))[0],
                "orders_total_usdt": float(orders_by_user.get(u.id, (0, 0))[1]),
                "referrals_count": referrals_by_user.get(u.id, 0),
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ],
    }


@router.get("/{user_id}")
async def user_card(
    user_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Карточка: заказы, сделки, рефералы, выводы, счета."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    orders = (await db.execute(
        select(Order)
        .where(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
        .limit(50)
    )).scalars().all()

    deals = (await db.execute(
        select(Deal)
        .where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id))
        .order_by(Deal.created_at.desc())
        .limit(50)
    )).scalars().all()

    referrals = (await db.execute(
        select(User).where(User.referrer_id == user.id).limit(100)
    )).scalars().all()

    withdrawals = (await db.execute(
        select(Withdrawal)
        .where(Withdrawal.user_id == user.id)
        .order_by(Withdrawal.created_at.desc())
        .limit(50)
    )).scalars().all()

    accounts = (await db.execute(
        select(Account).where(
            Account.owner_type == AccountOwnerType.USER,
            Account.owner_id == user.id,
        )
    )).scalars().all()

    referrer = await db.get(User, user.referrer_id) if user.referrer_id else None

    seller = (await db.execute(
        select(SellerProfile).where(SellerProfile.user_id == user.id)
    )).scalars().first()

    accrued = (await db.execute(
        select(func.coalesce(func.sum(ReferralTransaction.amount), 0))
        .where(ReferralTransaction.referrer_id == user.id)
    )).scalar() or 0

    return {
        "id": str(user.id),
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "language_code": user.language_code,
        "is_admin": user.is_admin,
        "is_blocked": user.is_blocked,
        "referral_code": user.referral_code,
        "referral_earnings": user.referral_earnings,
        "referral_accrued_total": str(accrued),
        "created_at": user.created_at.isoformat(),
        "referrer": None if referrer is None else {
            "id": str(referrer.id),
            "telegram_id": referrer.telegram_id,
            "username": referrer.username,
        },
        "seller": None if seller is None else {
            "display_name": seller.display_name,
            "status": seller.status.value,
            "rating": seller.rating,
            "deals_completed": seller.deals_completed,
            "payout_wallet": seller.payout_wallet,
        },
        "accounts": [
            {
                "currency": a.currency,
                "balance": str(from_minor(a.balance_minor, a.currency)),
                "hold": str(from_minor(a.hold_minor, a.currency)),
            }
            for a in accounts
        ],
        "orders": [
            {
                "id": str(o.id),
                "total_usdt": float(o.total_usdt),
                "status": o.status.value,
                "created_at": o.created_at.isoformat(),
            }
            for o in orders
        ],
        "deals": [
            {
                "id": str(d.id),
                "number": d.number,
                "role": "buyer" if d.buyer_id == user.id else "seller",
                "product_name": d.product_name,
                "status": d.status.value,
                "created_at": d.created_at.isoformat(),
            }
            for d in deals
        ],
        "referrals": [
            {
                "id": str(r.id),
                "telegram_id": r.telegram_id,
                "username": r.username,
                "created_at": r.created_at.isoformat(),
            }
            for r in referrals
        ],
        "withdrawals": [
            {
                "id": str(w.id),
                "amount": float(w.amount),
                "status": w.status.value if hasattr(w.status, "value") else str(w.status),
                "created_at": w.created_at.isoformat(),
            }
            for w in withdrawals
        ],
    }


@router.post("/{user_id}/block")
async def block_user(
    user_id: uuid.UUID,
    payload: BlockRequest,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Блокировка и разблокировка.

    Заблокированный не проходит ни авторизацию, ни проверку токена (см.
    utils/auth.py), то есть теряет доступ к приложению целиком.

    Открытые сделки при этом не трогаем: деньги в escrow принадлежат сторонам,
    и решение по ним принимает администратор через разбор спора, а не кнопка
    блокировки.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user.is_admin:
        raise HTTPException(status_code=400, detail="Нельзя заблокировать администратора")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Нельзя заблокировать самого себя")

    user.is_blocked = payload.blocked
    await db.commit()

    open_deals = 0
    if payload.blocked:
        open_deals = (await db.execute(
            select(func.count(Deal.id)).where(
                or_(Deal.buyer_id == user.id, Deal.seller_id == user.id),
                Deal.status.notin_([
                    DealStatus.RELEASED, DealStatus.REFUNDED, DealStatus.CANCELLED,
                ]),
            )
        )).scalar() or 0

    return {
        "id": str(user.id),
        "is_blocked": user.is_blocked,
        # Предупреждение администратору: у человека остались сделки, которые
        # он теперь не может закрыть сам
        "open_deals": open_deals,
    }
