import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, DateTime, Enum, ForeignKey, Index, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class AccountOwnerType(str, PyEnum):
    """
    Кому принадлежит счёт.

    EXTERNAL — единственный системный счёт, представляющий внешний мир
    (блокчейн, кошельки пользователей вне системы). Нужен, чтобы работала
    настоящая двойная запись: деньги не «появляются», а приходят с внешнего
    счёта, и не «исчезают», а уходят на него. Благодаря этому сумма всех
    проводок в журнале всегда равна нулю — на этом строится сверка.
    """
    EXTERNAL = "external"
    PLATFORM = "platform"
    USER = "user"


class LedgerEntryType(str, PyEnum):
    """Тип операции. Нужен для отчётности и разбора «из чего сложился баланс»."""
    OPENING_BALANCE = "opening_balance"        # перенос остатка из старой схемы
    PAYMENT_IN = "payment_in"                  # платёж покупателя пришёл на платформу
    COMMISSION = "commission"                  # комиссия платформы
    SELLER_ACCRUAL = "seller_accrual"          # начисление продавцу (P2P)
    AUTHOR_ACCRUAL = "author_accrual"          # начисление автору канала (подписки)
    REFERRAL_ACCRUAL = "referral_accrual"      # реферальное начисление
    ESCROW_HOLD = "escrow_hold"                # заморозка на время сделки
    ESCROW_RELEASE = "escrow_release"          # разморозка в пользу продавца
    ESCROW_REFUND = "escrow_refund"            # возврат покупателю
    WITHDRAWAL_RESERVE = "withdrawal_reserve"  # резерв под заявку на вывод
    WITHDRAWAL_COMPLETE = "withdrawal_complete"
    WITHDRAWAL_CANCEL = "withdrawal_cancel"
    MANUAL_ADJUST = "manual_adjust"            # ручная корректировка админом


class LedgerRefType(str, PyEnum):
    """К какой сущности относится проводка."""
    ORDER = "order"
    DEAL = "deal"
    SUBSCRIPTION = "subscription"
    WITHDRAWAL = "withdrawal"
    MIGRATION = "migration"
    MANUAL = "manual"


class Account(Base):
    """
    Внутренний счёт-баланс.

    balance_minor и hold_minor — денормализованные суммы, они ОБЯЗАНЫ совпадать
    с суммой проводок по счёту (это проверяет finance_service.reconcile()).
    Источник правды — журнал ledger_entries, а не эти поля.

    Суммы в минорных единицах валюты (см. services/money.py): для TON нанотоны,
    для USD центы. Целые числа, никакого float.
    """
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    owner_type: Mapped[AccountOwnerType] = mapped_column(
        Enum(AccountOwnerType, native_enum=False, length=20), nullable=False
    )
    # NULL для системных счетов (external, platform)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )

    currency: Mapped[str] = mapped_column(String(10), nullable=False)

    balance_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    # Часть баланса, заблокированная под escrow или заявку на вывод.
    # Доступно к трате = balance_minor - hold_minor.
    hold_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry", back_populates="account", cascade="all, delete-orphan"
    )
    owner: Mapped["User | None"] = relationship("User")

    __table_args__ = (
        # Один счёт на пару (владелец, валюта). Системные счета отличаются
        # owner_type при owner_id IS NULL.
        UniqueConstraint("owner_type", "owner_id", "currency", name="uq_account_owner_currency"),
        Index("ix_accounts_owner", "owner_type", "owner_id"),
    )

    @property
    def available_minor(self) -> int:
        return self.balance_minor - self.hold_minor

    def __repr__(self) -> str:
        return (
            f"<Account({self.owner_type.value}:{self.owner_id} "
            f"{self.balance_minor} {self.currency}, hold={self.hold_minor})>"
        )


class LedgerEntry(Base):
    """
    Запись журнала. Неизменяема: ошибочная проводка исправляется встречной,
    а не редактированием — иначе теряется история и разваливается сверка.
    """
    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    # Дублируем валюту: защищает от проводки в чужой валюте и упрощает отчёты
    currency: Mapped[str] = mapped_column(String(10), nullable=False)

    # Со знаком: + приход, − расход
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Изменение замороженной части (escrow, резерв под вывод)
    hold_delta_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )

    entry_type: Mapped[LedgerEntryType] = mapped_column(
        Enum(LedgerEntryType, native_enum=False, length=30), nullable=False
    )
    ref_type: Mapped[LedgerRefType] = mapped_column(
        Enum(LedgerRefType, native_enum=False, length=20), nullable=False
    )
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Ключ идемпотентности. UNIQUE на уровне БД — единственная надёжная защита
    # от двойного начисления при повторном вебхуке, ретрае или гонке.
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    account: Mapped["Account"] = relationship("Account", back_populates="entries")

    __table_args__ = (
        Index("ix_ledger_account_created", "account_id", "created_at"),
        Index("ix_ledger_ref", "ref_type", "ref_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<LedgerEntry({self.entry_type.value} {self.amount_minor:+d} "
            f"{self.currency} ref={self.ref_type.value}:{self.ref_id})>"
        )
