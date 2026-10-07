"""
Вывод денег пользователям.

Деньги лежат на кошельке площадки, а приватного ключа от него на сервере нет
и не будет: при взломе сервера иначе увели бы всё. Поэтому выплату
подписывает человек — админ нажимает «Выплатить», кошелёк площадки через
TonConnect предлагает готовый перевод (адрес, сумма, комментарий), админ
подтверждает. Сервер узнаёт о выплате из блокчейна: перевод с комментарием
заявки найден — заявка закрывается, человеку приходит сообщение.

Комиссию сети за перевод платит площадка: пользователь получает ровно ту
сумму, которую выводил.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.finance import Account, AccountOwnerType, LedgerEntryType, LedgerRefType
from models.user import User
from models.withdrawal import Withdrawal, WithdrawalStatus
from services import finance_service, ton_service
from services.money import format_amount, from_minor, to_minor

logger = logging.getLogger(__name__)


class WithdrawalError(Exception):
    pass


def amount_minor(w: Withdrawal) -> int:
    """Точная сумма заявки. У самых старых заявок её нет — тогда из float."""
    if w.amount_minor is not None:
        return w.amount_minor
    from decimal import Decimal
    return to_minor(Decimal(str(w.amount)), w.currency or "USD")


def sync_balance_cache(user: User, account: Account) -> None:
    """
    users.referral_earnings — кеш реферального баланса в USD для старого API.
    Заработок в TON туда не попадает: в одном поле сложились бы две валюты.
    """
    if account.currency != "USD":
        return
    user.referral_earnings = float(from_minor(account.available_minor, "USD"))


def new_payout_comment() -> str:
    """Комментарий перевода: короткий, уникальный, без внутренних id."""
    return f"MP-OUT-{secrets.token_hex(5).upper()}"


async def complete(db: AsyncSession, w: Withdrawal, *, tx_hash: str | None = None) -> bool:
    """
    Деньги ушли: списываем замороженную сумму со счёта пользователя.

    Идемпотентно — повторный вызов (двойной клик, гонка с фоновой проверкой)
    второй раз не спишет. Возвращает True, если заявка закрылась сейчас.
    """
    if w.status == WithdrawalStatus.COMPLETED:
        return False
    if w.status == WithdrawalStatus.REJECTED:
        raise WithdrawalError("Заявка отклонена — деньги уже вернулись на баланс")

    currency = w.currency or "USD"
    account = await finance_service.user_account(db, w.user_id, currency)
    await finance_service.withdraw_to_external(
        db,
        account=account,
        amount_minor=amount_minor(w),
        ref_type=LedgerRefType.WITHDRAWAL,
        ref_id=w.id,
        comment=f"Вывод {currency} на {w.wallet}",
    )
    w.status = WithdrawalStatus.COMPLETED
    w.completed_at = datetime.utcnow()
    if tx_hash:
        w.tx_hash = tx_hash

    user = await db.get(User, w.user_id)
    if user is not None:
        sync_balance_cache(user, account)
    return True


async def reject(db: AsyncSession, w: Withdrawal, reason: str) -> None:
    """Отказ: заморозка снимается, деньги снова доступны на балансе."""
    if w.status != WithdrawalStatus.PENDING:
        raise WithdrawalError(
            "Отклонить можно только заявку, которая ещё не выплачивалась. "
            "Если перевод отправлен, дождитесь его или отметьте, что он не прошёл."
        )
    currency = w.currency or "USD"
    account = await finance_service.user_account(db, w.user_id, currency)
    await finance_service.release_hold(
        db,
        account=account,
        amount_minor=amount_minor(w),
        # Свой тип, а не WITHDRAWAL_RESERVE: ключ идемпотентности собирается
        # из типа и основания, и с тем же типом разморозка совпала бы с
        # заморозкой и была бы молча отброшена как повтор
        entry_type=LedgerEntryType.WITHDRAWAL_CANCEL,
        ref_type=LedgerRefType.WITHDRAWAL,
        ref_id=w.id,
        comment=f"Заявка на вывод отклонена: {reason}",
    )
    w.status = WithdrawalStatus.REJECTED
    w.reject_reason = reason

    user = await db.get(User, w.user_id)
    if user is not None:
        sync_balance_cache(user, account)


# ---------------------------------------------------------------------------
# Уведомления
# ---------------------------------------------------------------------------

def _amount_text(w: Withdrawal) -> str:
    currency = w.currency or "USD"
    if currency == "TON":
        return format_amount(amount_minor(w), "TON")
    return f"{from_minor(amount_minor(w), currency)} USDT"


async def notify(db: AsyncSession, w: Withdrawal) -> None:
    """Сообщение человеку о судьбе заявки — на языке, выбранном в приложении."""
    from services.deal_chat_service import language_of
    from services.telegram_service import telegram_service

    user = await db.get(User, w.user_id)
    if user is None:
        return
    en = language_of(user) == "en"
    amount = _amount_text(w)

    if w.status == WithdrawalStatus.COMPLETED:
        text = (
            f"Withdrawal sent: {amount}\nWallet: {w.wallet}" if en
            else f"Средства выведены: {amount}\nКошелёк: {w.wallet}"
        )
    elif w.status == WithdrawalStatus.REJECTED:
        text = (
            f"Withdrawal of {amount} was declined: {w.reject_reason}\n"
            "The money is back on your balance." if en
            else f"Заявка на вывод {amount} отклонена: {w.reject_reason}\n"
            "Деньги вернулись на баланс."
        )
    else:
        return

    try:
        await telegram_service.send_message(user.telegram_id, text, parse_mode=None)
    except Exception as e:
        logger.warning("[WITHDRAWAL] Уведомление о заявке %s не доставлено: %s", w.id, e)


# ---------------------------------------------------------------------------
# Поиск выплат в блокчейне
# ---------------------------------------------------------------------------

async def confirm_sent_payouts(db: AsyncSession) -> int:
    """
    Закрывает заявки, перевод по которым уже в блокчейне.

    Смотрит и SENDING, и PENDING с комментарием: если админ пометил перевод
    как «не прошёл», а он всё-таки дошёл позже, заявка закроется сама и не
    будет выплачена второй раз.
    """
    waiting = (
        await db.execute(
            select(Withdrawal).where(
                Withdrawal.currency == "TON",
                Withdrawal.payout_comment.isnot(None),
                Withdrawal.status.in_([WithdrawalStatus.SENDING, WithdrawalStatus.PENDING]),
            )
        )
    ).scalars().all()
    if not waiting:
        return 0

    try:
        transfers = await ton_service.fetch_outgoing_transfers()
    except (ton_service.TonError, ton_service.TonNotConfigured) as e:
        logger.warning("[WITHDRAWAL] Не удалось проверить выплаты: %s", e)
        return 0

    by_comment: dict[str, ton_service.OutTransfer] = {}
    for transfer in transfers:
        by_comment.setdefault(transfer.comment, transfer)

    closed: list[Withdrawal] = []
    for w in waiting:
        transfer = by_comment.get(w.payout_comment or "")
        if transfer is None:
            continue
        if transfer.value_nano < amount_minor(w):
            logger.error(
                "[WITHDRAWAL] Перевод по заявке %s меньше заявки: %s < %s",
                w.id, transfer.value_nano, amount_minor(w),
            )
            continue
        if await complete(db, w, tx_hash=transfer.tx_hash):
            closed.append(w)

    if closed:
        await db.commit()
        for w in closed:
            await notify(db, w)
        logger.info("[WITHDRAWAL] Подтверждено выплат: %d", len(closed))
    return len(closed)


# ---------------------------------------------------------------------------
# Сводка для админки
# ---------------------------------------------------------------------------

async def ton_summary(db: AsyncSession) -> dict:
    """
    Сколько денег на кошельке площадки чьи.

    На кошельке лежат не только деньги площадки: там же замороженные суммы
    сделок и балансы пользователей. Своё — остаток после них. Считаем от
    настоящего баланса кошелька, а не от журнала: так в цифре сразу учтены
    реферальные (их площадка платит из своей доли) и комиссии сети за выплаты.
    """
    users_nano = (
        await db.execute(
            select(func.coalesce(func.sum(Account.balance_minor), 0)).where(
                Account.owner_type == AccountOwnerType.USER, Account.currency == "TON",
            )
        )
    ).scalar() or 0
    withdrawals_nano = (
        await db.execute(
            select(func.coalesce(func.sum(Account.hold_minor), 0)).where(
                Account.owner_type == AccountOwnerType.USER, Account.currency == "TON",
            )
        )
    ).scalar() or 0
    platform = await finance_service.platform_account(db, "TON")
    escrow_nano = platform.hold_minor

    wallet_nano: int | None
    try:
        wallet_nano = await ton_service.fetch_wallet_balance()
    except (ton_service.TonError, ton_service.TonNotConfigured) as e:
        logger.warning("[WITHDRAWAL] Баланс кошелька площадки недоступен: %s", e)
        wallet_nano = None

    owed = int(users_nano) + int(escrow_nano)
    return {
        "wallet_nano": wallet_nano,
        "users_nano": int(users_nano),
        "withdrawals_nano": int(withdrawals_nano),
        "escrow_nano": int(escrow_nano),
        "owed_nano": owed,
        "free_nano": None if wallet_nano is None else wallet_nano - owed,
    }
