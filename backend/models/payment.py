import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, DateTime, Enum, ForeignKey, Index, Numeric, String, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class PaymentStatus(str, PyEnum):
    """
    Жизненный цикл платежа.

    SEEN отделён от CONFIRMED специально: транзакция может появиться в
    индексере раньше, чем мы готовы выдавать товар (настройка
    ton_min_confirm_sec). Это даёт место для выдержки, не смешивая
    «увидели» и «зачли».
    """
    PENDING = "pending"        # счёт выставлен, ждём перевод
    SEEN = "seen"              # транзакция найдена в блокчейне, идёт выдержка
    CONFIRMED = "confirmed"    # зачтено, товар можно выдавать
    UNDERPAID = "underpaid"    # пришло меньше ожидаемого — разбор вручную
    EXPIRED = "expired"        # срок вышел, перевода не было
    FAILED = "failed"


class Payment(Base):
    """
    Платёж по заказу.

    Таблица существовала в схеме, но не использовалась ни строчкой кода —
    при CryptoBot данные инвойса складывались прямо в orders. Теперь это
    полноценный журнал платежей.

    Суммы в нанотонах (целые). Курс фиксируется в момент выставления счёта и
    живёт ton_rate_ttl_sec секунд: иначе сумма к оплате «плавала» бы между
    показом цены и подписью транзакции в кошельке.
    """
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    provider: Mapped[str] = mapped_column(
        String(50), default="ton_connect", server_default=text("'ton_connect'"), nullable=False
    )
    currency: Mapped[str] = mapped_column(
        String(10), default="TON", server_default=text("'TON'"), nullable=False
    )

    # --- Legacy CryptoBot ---------------------------------------------------
    # Оставлены, чтобы не потерять историю платежей до перехода на TON Connect.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- TON ----------------------------------------------------------------
    amount_nano: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    usd_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Курс с большой точностью: при 9 знаках у TON округление курса до центов
    # даёт заметную ошибку в итоговой сумме
    rate_usd_per_ton: Mapped[Decimal | None] = mapped_column(Numeric(20, 9), nullable=True)
    rate_locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    destination_address: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Уникальный текстовый комментарий — по нему платёж сопоставляется с
    # транзакцией в блокчейне. UNIQUE обязателен: совпадение комментариев
    # означало бы зачёт чужого платежа.
    payment_comment: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)

    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=20),
        default=PaymentStatus.PENDING, nullable=False,
    )

    # UNIQUE по хешу транзакции — защита от повторного зачёта одного перевода
    tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    tx_lt: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    from_address: Mapped[str | None] = mapped_column(String(80), nullable=True)
    received_nano: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    order: Mapped["Order"] = relationship("Order", back_populates="payments")

    __table_args__ = (
        Index("ix_payments_status_expires", "status", "expires_at"),
        Index("ix_payments_order", "order_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Payment(order={self.order_id}, {self.amount_nano} nanoTON, "
            f"status={self.status.value})>"
        )
