from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
import uuid
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from typing import Optional

from database import get_db
from models.finance import Account, AccountOwnerType, LedgerEntryType, LedgerRefType
from models.user import User
from models.withdrawal import Withdrawal, WithdrawalStatus
from schemas.withdrawal import WithdrawalCreate, WithdrawalUpdate, WithdrawalResponse
from utils.auth import get_current_user, require_admin
from services import finance_service
from services.money import from_minor, to_minor
from services.telegram_service import telegram_service

router = APIRouter(prefix="/api/withdrawals", tags=["Withdrawals"])

# Реферальные балансы номинированы в USD (см. миграцию d9e3f4a5b6c7),
# заработок продавцов и авторов каналов — в TON.
WITHDRAWAL_CURRENCY = "USD"
ALLOWED_CURRENCIES = ("USD", "TON")


def _sync_balance_cache(user: User, account: Account) -> None:
    """
    users.referral_earnings — денормализованный кеш для существующего API и
    фронта. Держим в нём ДОСТУПНУЮ сумму (баланс минус заморозка), чтобы
    поведение совпадало с прежним: заявка на вывод сразу уменьшает
    показываемый баланс.

    Кеш относится только к реферальному балансу в USD: заработок в TON в
    referral_earnings не отражается, иначе в одном поле сложились бы две
    разные валюты.
    """
    if account.currency != WITHDRAWAL_CURRENCY:
        return
    user.referral_earnings = float(
        from_minor(account.available_minor, WITHDRAWAL_CURRENCY)
    )


@router.get("/balance")
async def my_balances(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Доступные к выводу суммы по валютам.

    Нужен тем, у кого нет профиля продавца: заработок автора канала лежит на
    том же счёте, но увидеть его было негде — кабинет продавца показывает
    баланс только зарегистрированным продавцам, а в профиле выводится
    реферальный баланс в USD. Автор, продавший подписки, своих денег не видел.

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

    return {
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


@router.post("", response_model=WithdrawalResponse)
async def request_withdrawal(
    withdrawal_data: WithdrawalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Заявка на вывод реферального баланса.

    Раньше сумма просто вычиталась из users.referral_earnings. Если заявку не
    подтверждали, деньги нигде не числились: с баланса ушли, на вывод не
    отправились, следа операции не осталось.

    Теперь сумма замораживается на счёте: баланс остаётся, но становится
    недоступен к повторной заявке. Списание происходит в момент подтверждения
    вывода админом, и каждый шаг попадает в журнал.
    """
    currency = (withdrawal_data.currency or WITHDRAWAL_CURRENCY).upper()
    if currency not in ALLOWED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Валюта {currency} не поддерживается")

    account = await finance_service.user_account(db, user.id, currency)
    amount_minor = to_minor(withdrawal_data.amount, currency)

    if amount_minor <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    if amount_minor > account.available_minor:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Недостаточно средств: доступно "
                f"{from_minor(account.available_minor, currency)} {currency}"
            ),
        )

    withdrawal = Withdrawal(
        id=uuid.uuid4(),
        user_id=user.id,
        amount=float(withdrawal_data.amount),
        amount_minor=amount_minor,
        currency=currency,
        wallet=withdrawal_data.wallet,
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

    _sync_balance_cache(user, account)
    db.add(user)
    await db.commit()
    await db.refresh(withdrawal)

    # Notify admin
    try:
        user_id_display = f"@{user.username}" if user.username else str(user.telegram_id)
        await telegram_service.send_withdrawal_request_notification(
            user_identifier=user_id_display,
            wallet=withdrawal.wallet,
            amount=withdrawal.amount,
            balance_after=float(user.referral_earnings)
        )
    except Exception as e:
        print(f"[WITHDRAWAL] Failed to send admin notification: {e}")
    
    return WithdrawalResponse.model_validate(withdrawal)


@router.get("/my", response_model=list[WithdrawalResponse])
async def get_my_withdrawals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's withdrawal history"""
    stmt = select(Withdrawal).where(Withdrawal.user_id == user.id).order_by(Withdrawal.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/admin/all", response_model=dict)
async def get_all_withdrawals(
    status: Optional[WithdrawalStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get all withdrawals for admin with pagination and filtering"""
    stmt = select(Withdrawal).options(selectinload(Withdrawal.user)).order_by(Withdrawal.created_at.desc())
    
    if status:
        stmt = stmt.where(Withdrawal.status == status)
        
    # Count total for pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Get paginated results
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    withdrawals = result.scalars().all()
    
    # Format response
    items = []
    for w in withdrawals:
        data = WithdrawalResponse.model_validate(w)
        data.user_first_name = w.user.first_name
        data.user_telegram_id = w.user.telegram_id
        items.append(data)
        
    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.patch("/admin/{withdrawal_id}", response_model=WithdrawalResponse)
async def update_withdrawal_status(
    withdrawal_id: UUID,
    update_data: WithdrawalUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Update withdrawal status (admin only)"""
    stmt = select(Withdrawal).options(selectinload(Withdrawal.user)).where(Withdrawal.id == withdrawal_id)
    result = await db.execute(stmt)
    withdrawal = result.scalar_one_or_none()
    
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal request not found")
        
    if withdrawal.status == update_data.status:
        return withdrawal
        
    withdrawal.status = update_data.status
    if update_data.status == WithdrawalStatus.COMPLETED:
        withdrawal.completed_at = datetime.utcnow()

        # Фактическое списание: снимаем заморозку и уводим сумму на внешний
        # счёт. Идемпотентно по ключу заявки — повторное подтверждение
        # (двойной клик, ретрай) не спишет деньги дважды.
        currency = withdrawal.currency or WITHDRAWAL_CURRENCY
        account = await finance_service.user_account(db, withdrawal.user_id, currency)

        # amount_minor — точная сумма, записанная при создании заявки. У старых
        # заявок его нет, и приходится пересчитывать из float-поля: для USD с
        # двумя знаками это безопасно, а новые заявки так не считаются.
        amount_minor = withdrawal.amount_minor
        if amount_minor is None:
            amount_minor = to_minor(Decimal(str(withdrawal.amount)), currency)

        await finance_service.withdraw_to_external(
            db,
            account=account,
            amount_minor=amount_minor,
            ref_type=LedgerRefType.WITHDRAWAL,
            ref_id=withdrawal.id,
            comment=f"Вывод {currency} на {withdrawal.wallet}",
        )
        _sync_balance_cache(withdrawal.user, account)
        db.add(withdrawal.user)

        # Notify user via Telegram
        try:
            label = "USDT" if currency == WITHDRAWAL_CURRENCY else currency
            precision = 2 if currency == WITHDRAWAL_CURRENCY else 9
            message = (
                f"<b>Средства выведены.</b>\n"
                f"Кошелек - <code>{withdrawal.wallet}</code>\n"
                f"Сумма - {withdrawal.amount:.{precision}f} {label}"
            )
            await telegram_service.send_message(withdrawal.user.telegram_id, message)
        except Exception as e:
            print(f"[WITHDRAWAL] Error sending notification: {e}")
            
    db.add(withdrawal)
    await db.commit()
    await db.refresh(withdrawal)
    
    # Attach user info for response
    data = WithdrawalResponse.model_validate(withdrawal)
    data.user_first_name = withdrawal.user.first_name
    data.user_telegram_id = withdrawal.user.telegram_id
    
    return data
