"""
Вывод денег: заявка пользователя и выплата из админки.

Баланс один — в TON: заработок продавца, автора канала, возвраты покупателю
и реферальные. Выводится на кошелёк, подключённый в приложении через
TonConnect. Выплату подписывает админ в кошельке площадки (тоже через
TonConnect), а сервер находит перевод в блокчейне и закрывает заявку —
подробности в services/withdrawal_service.py.

Старые реферальные заявки в USD (на USDT TRC20) по-прежнему проходят: API
их принимает, админ закрывает их вручную.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import get_db
from models.finance import Account, AccountOwnerType, LedgerEntryType, LedgerRefType
from models.user import User
from models.withdrawal import Withdrawal, WithdrawalStatus
from schemas.withdrawal import WithdrawalCreate, WithdrawalResponse, WithdrawalUpdate
from services import finance_service, settings_service, ton_address, withdrawal_service
from services.money import TON_LABEL, from_minor, to_minor
from services.telegram_service import telegram_service
from utils.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/withdrawals", tags=["Withdrawals"])

# По умолчанию — USD: так работает старый вызов реферального вывода.
# Новое приложение всегда передаёт TON
WITHDRAWAL_CURRENCY = "USD"
ALLOWED_CURRENCIES = ("USD", "TON")

# Сколько живёт перевод, подготовленный для подписи в кошельке
PAYOUT_TTL = timedelta(minutes=10)


@router.get("/balance")
async def my_balances(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Доступные к выводу суммы по валютам.

    Счета читаем напрямую и НЕ заводим отсутствующие: GET-запрос не должен
    ничего создавать, иначе у каждого заглянувшего появлялся бы пустой счёт.
    """
    rows = (
        await db.execute(
            select(Account).where(
                Account.owner_type == AccountOwnerType.USER,
                Account.owner_id == user.id,
                Account.currency.in_(ALLOWED_CURRENCIES),
            )
        )
    ).scalars().all()

    by_currency = {a.currency: a for a in rows}
    result = {
        currency: {
            "available": str(from_minor(
                by_currency[currency].available_minor if currency in by_currency else 0,
                currency,
            )),
            "available_minor": (
                by_currency[currency].available_minor if currency in by_currency else 0
            ),
            "hold_minor": by_currency[currency].hold_minor if currency in by_currency else 0,
        }
        for currency in ALLOWED_CURRENCIES
    }
    # Минимальная сумма вывода — чтобы форма проверила её до отправки
    min_nano = await settings_service.get_int(db, "payout_min_ton_nano")
    result["TON"]["min_withdrawal"] = str(from_minor(min_nano, "TON"))
    return result


@router.post("", response_model=WithdrawalResponse)
async def request_withdrawal(
    withdrawal_data: WithdrawalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Заявка на вывод.

    Сумма замораживается на счёте: баланс остаётся, но повторно её не
    вывести. Списание — когда выплата найдена в блокчейне или админ отметил
    её вручную; отказ возвращает деньги на баланс.
    """
    currency = (withdrawal_data.currency or WITHDRAWAL_CURRENCY).upper()
    if currency not in ALLOWED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Валюта {currency} не поддерживается")

    wallet = withdrawal_data.wallet.strip()
    amount_minor = to_minor(withdrawal_data.amount, currency)
    if amount_minor <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    if currency == "TON":
        # Ошибка в адресе — деньги, ушедшие в никуда: проверяем до заморозки
        if not ton_address.is_valid(wallet):
            raise HTTPException(status_code=400, detail="Адрес кошелька записан неверно")
        min_nano = await settings_service.get_int(db, "payout_min_ton_nano")
        if amount_minor < min_nano:
            raise HTTPException(
                status_code=400,
                detail=f"Минимальная сумма вывода — {from_minor(min_nano, 'TON')} {TON_LABEL}",
            )

    account = await finance_service.user_account(db, user.id, currency)
    if amount_minor > account.available_minor:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Недостаточно средств: доступно "
                f"{from_minor(account.available_minor, currency)} "
                f"{TON_LABEL if currency == 'TON' else currency}"
            ),
        )

    withdrawal = Withdrawal(
        id=uuid.uuid4(),
        user_id=user.id,
        amount=float(withdrawal_data.amount),
        amount_minor=amount_minor,
        currency=currency,
        wallet=wallet,
        status=WithdrawalStatus.PENDING
    )
    db.add(withdrawal)
    await db.flush()  # нужен id заявки для ссылки в проводке

    await finance_service.hold(
        db,
        account=account,
        amount_minor=amount_minor,
        entry_type=LedgerEntryType.WITHDRAWAL_RESERVE,
        ref_type=LedgerRefType.WITHDRAWAL,
        ref_id=withdrawal.id,
        comment=f"Резерв под заявку на вывод {currency} на {withdrawal.wallet}",
    )

    withdrawal_service.sync_balance_cache(user, account)
    db.add(user)
    await db.commit()
    await db.refresh(withdrawal)

    try:
        user_id_display = f"@{user.username}" if user.username else str(user.telegram_id)
        await telegram_service.send_withdrawal_request_notification(
            user_identifier=user_id_display,
            wallet=withdrawal.wallet,
            amount=withdrawal.amount,
            balance_after=float(from_minor(account.available_minor, currency)),
        )
    except Exception as e:
        print(f"[WITHDRAWAL] Failed to send admin notification: {e}")

    return WithdrawalResponse.model_validate(withdrawal)


@router.get("/my", response_model=list[WithdrawalResponse])
async def get_my_withdrawals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Withdrawal).where(Withdrawal.user_id == user.id).order_by(Withdrawal.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Админка
# ---------------------------------------------------------------------------

def _admin_dto(w: Withdrawal) -> WithdrawalResponse:
    data = WithdrawalResponse.model_validate(w)
    data.user_first_name = w.user.first_name
    data.user_telegram_id = w.user.telegram_id
    return data


async def _get(db: AsyncSession, withdrawal_id: UUID) -> Withdrawal:
    w = (
        await db.execute(
            select(Withdrawal).options(selectinload(Withdrawal.user))
            .where(Withdrawal.id == withdrawal_id)
        )
    ).scalar_one_or_none()
    if w is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return w


@router.get("/admin/all", response_model=dict)
async def get_all_withdrawals(
    status: Optional[WithdrawalStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Заявки для админки. Вкладка «Новые» (status=pending) показывает и
    отправленные, но ещё не подтверждённые сетью: с ними тоже может
    понадобиться что-то сделать.
    """
    stmt = select(Withdrawal).options(selectinload(Withdrawal.user)).order_by(Withdrawal.created_at.desc())
    if status == WithdrawalStatus.PENDING:
        stmt = stmt.where(Withdrawal.status.in_([WithdrawalStatus.PENDING, WithdrawalStatus.SENDING]))
    elif status:
        stmt = stmt.where(Withdrawal.status == status)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    withdrawals = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()

    return {
        "items": [_admin_dto(w) for w in withdrawals],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/admin/summary")
async def payouts_summary(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Чьи деньги лежат на кошельке площадки и сколько из них можно забрать себе."""
    summary = await withdrawal_service.ton_summary(db)
    return {
        **{k: (str(v) if v is not None else None) for k, v in summary.items()},
        "platform_address": settings.TON_RECEIVING_ADDRESS.strip() or None,
        "network": settings.TON_NETWORK,
    }


@router.post("/admin/{withdrawal_id}/payout")
async def prepare_payout(
    withdrawal_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Перевод для подписи в кошельке площадки: адрес, сумма, комментарий.

    Комментарий выдаётся один раз на заявку и дальше не меняется: по нему
    перевод находится в блокчейне, в том числе если админ решил, что перевод
    не прошёл, а он дошёл позже.
    """
    w = await _get(db, withdrawal_id)
    if (w.currency or WITHDRAWAL_CURRENCY) != "TON":
        raise HTTPException(status_code=400, detail=f"Через кошелёк выплачиваются только заявки в {TON_LABEL}")
    if w.status != WithdrawalStatus.PENDING:
        raise HTTPException(status_code=400, detail="Заявка уже выплачивается или закрыта")

    if not w.payout_comment:
        w.payout_comment = withdrawal_service.new_payout_comment()
        await db.commit()

    return {
        "address": w.wallet,
        "amount_nano": str(withdrawal_service.amount_minor(w)),
        "comment": w.payout_comment,
        "valid_until": int((datetime.utcnow() + PAYOUT_TTL).timestamp()),
        "network": settings.TON_NETWORK,
        "platform_address": settings.TON_RECEIVING_ADDRESS.strip() or None,
    }


@router.post("/admin/{withdrawal_id}/sent", response_model=WithdrawalResponse)
async def payout_sent(
    withdrawal_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Кошелёк площадки подписал и отправил перевод — ждём его в блокчейне."""
    w = await _get(db, withdrawal_id)
    if w.status != WithdrawalStatus.PENDING or not w.payout_comment:
        raise HTTPException(status_code=400, detail="Заявка не готовилась к выплате через кошелёк")
    w.status = WithdrawalStatus.SENDING
    w.sent_at = datetime.utcnow()
    await db.commit()

    # Сеть подтверждает перевод за секунды — проверяем сразу, не дожидаясь
    # фоновой проверки
    await withdrawal_service.confirm_sent_payouts(db)
    await db.refresh(w)
    return _admin_dto(w)


class RejectIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/admin/{withdrawal_id}/reject", response_model=WithdrawalResponse)
async def reject_withdrawal(
    withdrawal_id: UUID,
    payload: RejectIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Отказ с причиной: деньги возвращаются на баланс, человеку — сообщение."""
    w = await _get(db, withdrawal_id)
    try:
        await withdrawal_service.reject(db, w, payload.reason.strip())
    except withdrawal_service.WithdrawalError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(w)
    await withdrawal_service.notify(db, w)
    return _admin_dto(w)


@router.patch("/admin/{withdrawal_id}", response_model=WithdrawalResponse)
async def update_withdrawal_status(
    withdrawal_id: UUID,
    update_data: WithdrawalUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Ручная смена статуса.

      * completed — перевод сделан вручную или отправленный через кошелёк
        дошёл, но не нашёлся автоматически;
      * pending — отправленный перевод не прошёл (в кошельке не хватило
        денег, админ отменил): заявка снова ждёт выплаты.
    """
    w = await _get(db, withdrawal_id)

    if update_data.status == WithdrawalStatus.COMPLETED:
        try:
            done = await withdrawal_service.complete(db, w)
        except withdrawal_service.WithdrawalError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await db.commit()
        await db.refresh(w)
        if done:
            await withdrawal_service.notify(db, w)
    elif update_data.status == WithdrawalStatus.PENDING:
        if w.status != WithdrawalStatus.SENDING:
            raise HTTPException(status_code=400, detail="Вернуть в ожидание можно только отправленную выплату")
        w.status = WithdrawalStatus.PENDING
        w.sent_at = None
        await db.commit()
        await db.refresh(w)
    elif update_data.status == WithdrawalStatus.REJECTED:
        raise HTTPException(status_code=400, detail="Для отказа нужна причина — /reject")
    elif update_data.status != w.status:
        raise HTTPException(status_code=400, detail="Такой переход статуса не поддерживается")

    return _admin_dto(w)
