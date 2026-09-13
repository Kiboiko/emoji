"""
Админские эндпоинты финансового слоя: настройки, счета, журнал, сверка.

UI для них появится на этапе 7 — здесь только API.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models.finance import Account, LedgerEntry, LedgerEntryType, LedgerRefType
from models.user import User
from services import finance_service, settings_service
from services.money import from_minor
from utils.auth import require_admin

router = APIRouter(prefix="/api/admin", tags=["Admin Finance"])


# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------

class SettingUpdate(BaseModel):
    value: Any


@router.get("/settings")
async def list_settings(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Все настройки с метаданными: тип, дефолт, границы, текущее значение."""
    current = await settings_service.get_all(db)
    return [{**meta, "value": current[meta["key"]]} for meta in settings_service.describe()]


@router.put("/settings/{key}")
async def update_setting(
    key: str,
    payload: SettingUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Меняет настройку. Значение валидируется по объявленному типу и границам —
    выставить комиссию 300% или отрицательный срок через API нельзя.
    """
    try:
        value = await settings_service.set_setting(db, key, payload.value, admin_id=admin.id)
    except settings_service.UnknownSettingKey:
        raise HTTPException(status_code=404, detail=f"Неизвестная настройка: {key}")
    except settings_service.SettingValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"key": key, "value": value}


# ---------------------------------------------------------------------------
# Счета и журнал
# ---------------------------------------------------------------------------

@router.get("/finance/accounts")
async def list_accounts(
    currency: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Account).options(selectinload(Account.owner))
    if currency:
        stmt = stmt.where(Account.currency == currency)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0

    rows = (
        await db.execute(
            stmt.order_by(Account.balance_minor.desc()).offset(skip).limit(limit)
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(a.id),
                "owner_type": a.owner_type.value,
                "owner_id": str(a.owner_id) if a.owner_id else None,
                "owner_username": a.owner.username if a.owner else None,
                "owner_telegram_id": a.owner.telegram_id if a.owner else None,
                "currency": a.currency,
                "balance_minor": a.balance_minor,
                "hold_minor": a.hold_minor,
                "available_minor": a.available_minor,
                "balance": str(from_minor(a.balance_minor, a.currency)),
                "hold": str(from_minor(a.hold_minor, a.currency)),
                "available": str(from_minor(a.available_minor, a.currency)),
            }
            for a in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/finance/ledger")
async def list_ledger(
    account_id: Optional[uuid.UUID] = Query(None),
    entry_type: Optional[LedgerEntryType] = Query(None),
    ref_type: Optional[LedgerRefType] = Query(None),
    ref_id: Optional[uuid.UUID] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Журнал операций. Отвечает на вопрос «из чего сложился этот баланс»."""
    stmt = select(LedgerEntry)
    if account_id:
        stmt = stmt.where(LedgerEntry.account_id == account_id)
    if entry_type:
        stmt = stmt.where(LedgerEntry.entry_type == entry_type)
    if ref_type:
        stmt = stmt.where(LedgerEntry.ref_type == ref_type)
    if ref_id:
        stmt = stmt.where(LedgerEntry.ref_id == ref_id)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0

    rows = (
        await db.execute(
            stmt.order_by(LedgerEntry.created_at.desc()).offset(skip).limit(limit)
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(e.id),
                "account_id": str(e.account_id),
                "currency": e.currency,
                "amount_minor": e.amount_minor,
                "amount": str(from_minor(e.amount_minor, e.currency)),
                "hold_delta_minor": e.hold_delta_minor,
                "entry_type": e.entry_type.value,
                "ref_type": e.ref_type.value,
                "ref_id": str(e.ref_id) if e.ref_id else None,
                "comment": e.comment,
                "created_at": e.created_at.isoformat(),
            }
            for e in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.post("/finance/reconcile")
async def run_reconcile(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Сверка: балансы против журнала и глобальный ноль по каждой валюте.
    Расхождение означает, что деньги двигали в обход финансового слоя.
    """
    report = await finance_service.reconcile(db)
    return {
        "ok": report.ok,
        "checked_accounts": report.checked_accounts,
        "global_sum_by_currency": report.global_sum_by_currency,
        "issues": [
            {
                "account_id": str(i.account_id),
                "field": i.field,
                "stored": i.stored,
                "computed": i.computed,
                "diff": i.stored - i.computed,
            }
            for i in report.issues
        ],
    }
