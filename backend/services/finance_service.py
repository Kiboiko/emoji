"""
Финансовый слой: счета, журнал проводок, сверка.

Принципы, которые здесь соблюдаются жёстко:

1. ДВОЙНАЯ ЗАПИСЬ. Любая операция — это набор проводок, сумма которых равна
   нулю. Деньги не появляются и не исчезают, они переходят между счетами.
   Внешний мир (блокчейн, кошельки пользователей) представлен системным
   счётом EXTERNAL, поэтому приход извне тоже балансируется.
   Следствие: сумма ВСЕХ проводок в журнале всегда 0 — это проверяет reconcile().

2. ЖУРНАЛ — ИСТОЧНИК ПРАВДЫ. Поля accounts.balance_minor / hold_minor —
   денормализация для быстрого чтения. Расхождение с журналом = баг,
   его ловит reconcile().

3. ИДЕМПОТЕНТНОСТЬ. У каждой проводки есть idempotency_key с UNIQUE в БД.
   Повторный вызов (ретрай вебхука, гонка двух воркеров, двойной клик) не
   создаёт второе начисление. Проверка «а нет ли уже такой записи» без UNIQUE
   не работает: между проверкой и вставкой успевает пролезть параллельный
   запрос.

4. ЦЕЛЫЕ ЧИСЛА. Только минорные единицы (нанотоны, центы). См. money.py.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.finance import (
    Account, AccountOwnerType, LedgerEntry, LedgerEntryType, LedgerRefType,
)

logger = logging.getLogger(__name__)


class FinanceError(Exception):
    pass


class UnbalancedTransaction(FinanceError):
    pass


class InsufficientFunds(FinanceError):
    pass


@dataclass
class Posting:
    """Одна проводка внутри операции."""
    account: Account
    entry_type: LedgerEntryType
    amount_minor: int = 0
    hold_delta_minor: int = 0
    comment: str | None = None
    # Позволяет развести две проводки одного типа по одному счёту в рамках
    # одной операции (например, две разные комиссии). Попадает в ключ.
    key_suffix: str = ""


@dataclass
class PostResult:
    entries: list[LedgerEntry] = field(default_factory=list)
    already_applied: bool = False


# ---------------------------------------------------------------------------
# Счета
# ---------------------------------------------------------------------------

async def get_or_create_account(
    db: AsyncSession,
    *,
    owner_type: AccountOwnerType,
    currency: str,
    owner_id: uuid.UUID | None = None,
) -> Account:
    """
    Возвращает счёт, создавая при необходимости.

    Гонку двух параллельных созданий ловим по UNIQUE(owner_type, owner_id,
    currency): проигравший повторно читает уже созданный счёт.
    """
    if owner_type == AccountOwnerType.USER and owner_id is None:
        raise FinanceError("Для пользовательского счёта нужен owner_id")
    if owner_type != AccountOwnerType.USER and owner_id is not None:
        raise FinanceError(f"У системного счёта {owner_type.value} не может быть owner_id")

    stmt = select(Account).where(
        Account.owner_type == owner_type,
        Account.owner_id == owner_id,
        Account.currency == currency,
    )
    account = (await db.execute(stmt)).scalar_one_or_none()
    if account is not None:
        return account

    account = Account(
        id=uuid.uuid4(), owner_type=owner_type, owner_id=owner_id, currency=currency
    )
    db.add(account)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        # Счёт успел создать параллельный запрос. Убираем свой объект из
        # сессии, иначе он всплывёт при следующем flush и уронит его снова.
        if account in db:
            db.expunge(account)
        account = (await db.execute(stmt)).scalar_one()
    return account


async def external_account(db: AsyncSession, currency: str) -> Account:
    return await get_or_create_account(
        db, owner_type=AccountOwnerType.EXTERNAL, currency=currency
    )


async def platform_account(db: AsyncSession, currency: str) -> Account:
    return await get_or_create_account(
        db, owner_type=AccountOwnerType.PLATFORM, currency=currency
    )


async def user_account(db: AsyncSession, user_id: uuid.UUID, currency: str) -> Account:
    return await get_or_create_account(
        db, owner_type=AccountOwnerType.USER, currency=currency, owner_id=user_id
    )


# ---------------------------------------------------------------------------
# Проводки
# ---------------------------------------------------------------------------

def _idempotency_key(
    ref_type: LedgerRefType, ref_id: uuid.UUID | None, posting: Posting
) -> str:
    parts = [
        ref_type.value,
        str(ref_id) if ref_id else "-",
        posting.entry_type.value,
        str(posting.account.id),
    ]
    if posting.key_suffix:
        parts.append(posting.key_suffix)
    return ":".join(parts)


async def post(
    db: AsyncSession,
    *,
    ref_type: LedgerRefType,
    ref_id: uuid.UUID | None,
    postings: list[Posting],
    comment: str | None = None,
    admin_id: uuid.UUID | None = None,
    require_balanced: bool = True,
    allow_negative: bool = False,
) -> PostResult:
    """
    Атомарно применяет набор проводок.

    Либо применяются все, либо ни одной. Если операция уже была применена
    раньше (совпал ключ идемпотентности), возвращается already_applied=True
    и ничего не меняется.

    Вызывающий код сам решает, когда делать commit — здесь только flush,
    чтобы операцию можно было включить в большую транзакцию (например,
    «оплатить заказ + выдать товар»).
    """
    if not postings:
        raise FinanceError("Пустой набор проводок")

    currencies = {p.account.currency for p in postings}
    if len(currencies) > 1:
        raise FinanceError(f"Проводки в разных валютах в одной операции: {currencies}")
    currency = currencies.pop()

    if require_balanced:
        total = sum(p.amount_minor for p in postings)
        if total != 0:
            raise UnbalancedTransaction(
                f"Сумма проводок не равна нулю: {total} {currency}. "
                "Приход извне оформляется через счёт EXTERNAL."
            )

    entries = [
        LedgerEntry(
            id=uuid.uuid4(),
            account_id=p.account.id,
            currency=currency,
            amount_minor=p.amount_minor,
            hold_delta_minor=p.hold_delta_minor,
            entry_type=p.entry_type,
            ref_type=ref_type,
            ref_id=ref_id,
            idempotency_key=_idempotency_key(ref_type, ref_id, p),
            comment=p.comment or comment,
            created_by_admin_id=admin_id,
        )
        for p in postings
    ]

    try:
        async with db.begin_nested():
            db.add_all(entries)
            await db.flush()
    except IntegrityError:
        # Сработал UNIQUE по idempotency_key — операция уже проведена.
        # Выкидываем свои записи из сессии, иначе они попробуют вставиться
        # при следующем flush и уронят уже чужую транзакцию.
        for entry in entries:
            if entry in db:
                db.expunge(entry)
        logger.info(
            "[FINANCE] Операция %s:%s уже применена, повтор проигнорирован",
            ref_type.value, ref_id,
        )
        return PostResult(already_applied=True)

    # Балансы двигаем атомарным UPDATE, а не чтением-записью в Python:
    # иначе два параллельных начисления затрут друг друга.
    for p in postings:
        await db.execute(
            update(Account)
            .where(Account.id == p.account.id)
            .values(
                balance_minor=Account.balance_minor + p.amount_minor,
                hold_minor=Account.hold_minor + p.hold_delta_minor,
            )
        )
    await db.flush()

    for p in postings:
        await db.refresh(p.account)
        _assert_account_sane(p.account, allow_negative=allow_negative)

    logger.info(
        "[FINANCE] %s:%s — %s",
        ref_type.value, ref_id,
        ", ".join(
            f"{p.entry_type.value} {p.amount_minor:+d}"
            + (f" hold{p.hold_delta_minor:+d}" if p.hold_delta_minor else "")
            for p in postings
        ),
    )
    return PostResult(entries=entries)


def _assert_account_sane(account: Account, *, allow_negative: bool) -> None:
    """
    Внешний счёт обязан уходить в минус — он представляет мир за пределами
    системы. Все остальные в минус уходить не должны.
    """
    if account.owner_type == AccountOwnerType.EXTERNAL or allow_negative:
        return
    if account.balance_minor < 0:
        raise InsufficientFunds(
            f"Баланс счёта {account.id} ушёл бы в минус: {account.balance_minor}"
        )
    if account.hold_minor < 0:
        raise FinanceError(f"Отрицательная заморозка на счёте {account.id}")
    if account.hold_minor > account.balance_minor:
        raise InsufficientFunds(
            f"Заморожено больше, чем есть на счёте {account.id}: "
            f"hold={account.hold_minor} > balance={account.balance_minor}"
        )


# ---------------------------------------------------------------------------
# Типовые операции
# ---------------------------------------------------------------------------

async def deposit_from_external(
    db: AsyncSession,
    *,
    account: Account,
    amount_minor: int,
    ref_type: LedgerRefType,
    ref_id: uuid.UUID | None,
    entry_type: LedgerEntryType = LedgerEntryType.PAYMENT_IN,
    comment: str | None = None,
) -> PostResult:
    """Приход денег извне (оплата покупателя) на внутренний счёт."""
    if amount_minor <= 0:
        raise FinanceError("Сумма зачисления должна быть положительной")

    ext = await external_account(db, account.currency)
    return await post(
        db,
        ref_type=ref_type,
        ref_id=ref_id,
        comment=comment,
        postings=[
            Posting(account=ext, entry_type=entry_type, amount_minor=-amount_minor),
            Posting(account=account, entry_type=entry_type, amount_minor=amount_minor),
        ],
    )


async def transfer(
    db: AsyncSession,
    *,
    src: Account,
    dst: Account,
    amount_minor: int,
    entry_type: LedgerEntryType,
    ref_type: LedgerRefType,
    ref_id: uuid.UUID | None,
    comment: str | None = None,
) -> PostResult:
    """Перевод между внутренними счетами."""
    if amount_minor <= 0:
        raise FinanceError("Сумма перевода должна быть положительной")

    return await post(
        db,
        ref_type=ref_type,
        ref_id=ref_id,
        comment=comment,
        postings=[
            Posting(account=src, entry_type=entry_type, amount_minor=-amount_minor,
                    key_suffix="src"),
            Posting(account=dst, entry_type=entry_type, amount_minor=amount_minor,
                    key_suffix="dst"),
        ],
    )


async def withdraw_to_external(
    db: AsyncSession,
    *,
    account: Account,
    amount_minor: int,
    ref_type: LedgerRefType,
    ref_id: uuid.UUID | None,
    entry_type: LedgerEntryType = LedgerEntryType.WITHDRAWAL_COMPLETE,
    release_hold: bool = True,
    comment: str | None = None,
) -> PostResult:
    """Вывод денег наружу: списание со счёта на внешний."""
    if amount_minor <= 0:
        raise FinanceError("Сумма вывода должна быть положительной")

    ext = await external_account(db, account.currency)
    return await post(
        db,
        ref_type=ref_type,
        ref_id=ref_id,
        comment=comment,
        postings=[
            Posting(
                account=account, entry_type=entry_type, amount_minor=-amount_minor,
                hold_delta_minor=-amount_minor if release_hold else 0,
            ),
            Posting(account=ext, entry_type=entry_type, amount_minor=amount_minor),
        ],
    )


async def hold(
    db: AsyncSession,
    *,
    account: Account,
    amount_minor: int,
    entry_type: LedgerEntryType,
    ref_type: LedgerRefType,
    ref_id: uuid.UUID | None,
    comment: str | None = None,
) -> PostResult:
    """
    Заморозка части баланса без движения денег (escrow, резерв под вывод).
    Сумма не меняется, меняется только доступная к трате часть.
    """
    if amount_minor <= 0:
        raise FinanceError("Сумма заморозки должна быть положительной")
    if account.available_minor < amount_minor:
        raise InsufficientFunds(
            f"Недостаточно свободных средств: доступно {account.available_minor}, "
            f"требуется {amount_minor}"
        )

    return await post(
        db,
        ref_type=ref_type,
        ref_id=ref_id,
        comment=comment,
        require_balanced=False,  # движения денег нет, только заморозка
        postings=[
            Posting(account=account, entry_type=entry_type, amount_minor=0,
                    hold_delta_minor=amount_minor),
        ],
    )


async def release_hold(
    db: AsyncSession,
    *,
    account: Account,
    amount_minor: int,
    entry_type: LedgerEntryType,
    ref_type: LedgerRefType,
    ref_id: uuid.UUID | None,
    comment: str | None = None,
) -> PostResult:
    """Снятие заморозки без движения денег."""
    if amount_minor <= 0:
        raise FinanceError("Сумма разморозки должна быть положительной")

    return await post(
        db,
        ref_type=ref_type,
        ref_id=ref_id,
        comment=comment,
        require_balanced=False,
        postings=[
            Posting(account=account, entry_type=entry_type, amount_minor=0,
                    hold_delta_minor=-amount_minor),
        ],
    )


# ---------------------------------------------------------------------------
# Сверка
# ---------------------------------------------------------------------------

@dataclass
class ReconcileIssue:
    account_id: uuid.UUID
    field: str
    stored: int
    computed: int

    def __str__(self) -> str:
        return (
            f"счёт {self.account_id}: {self.field} в accounts={self.stored}, "
            f"по журналу={self.computed}, расхождение {self.stored - self.computed:+d}"
        )


@dataclass
class ReconcileReport:
    checked_accounts: int = 0
    issues: list[ReconcileIssue] = field(default_factory=list)
    global_sum_by_currency: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues and all(v == 0 for v in self.global_sum_by_currency.values())


async def reconcile(db: AsyncSession) -> ReconcileReport:
    """
    Сверяет денормализованные балансы с журналом и проверяет глобальный ноль.

    Два независимых инварианта:
      1. по каждому счёту: balance_minor == сумма amount_minor его проводок
         (и то же для hold_minor);
      2. по каждой валюте: сумма ВСЕХ проводок == 0. Если не ноль — где-то
         деньги создались или пропали в обход двойной записи.
    """
    report = ReconcileReport()

    sums = (
        select(
            LedgerEntry.account_id,
            func.coalesce(func.sum(LedgerEntry.amount_minor), 0).label("amount"),
            func.coalesce(func.sum(LedgerEntry.hold_delta_minor), 0).label("hold"),
        )
        .group_by(LedgerEntry.account_id)
        .subquery()
    )

    rows = (
        await db.execute(
            select(Account, sums.c.amount, sums.c.hold).outerjoin(
                sums, sums.c.account_id == Account.id
            )
        )
    ).all()

    for account, amount, hold_sum in rows:
        report.checked_accounts += 1
        computed_balance = int(amount or 0)
        computed_hold = int(hold_sum or 0)
        if account.balance_minor != computed_balance:
            report.issues.append(
                ReconcileIssue(account.id, "balance_minor", account.balance_minor, computed_balance)
            )
        if account.hold_minor != computed_hold:
            report.issues.append(
                ReconcileIssue(account.id, "hold_minor", account.hold_minor, computed_hold)
            )

    totals = (
        await db.execute(
            select(LedgerEntry.currency, func.coalesce(func.sum(LedgerEntry.amount_minor), 0))
            .group_by(LedgerEntry.currency)
        )
    ).all()
    report.global_sum_by_currency = {cur: int(total) for cur, total in totals}

    if report.ok:
        logger.info("[FINANCE] Сверка сошлась, счетов проверено: %d", report.checked_accounts)
    else:
        logger.error(
            "[FINANCE] СВЕРКА НЕ СОШЛАСЬ. Расхождений: %d. Суммы по валютам: %s",
            len(report.issues), report.global_sum_by_currency,
        )
        for issue in report.issues[:20]:
            logger.error("[FINANCE]   %s", issue)

    return report
