import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, Float, Enum, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class WithdrawalStatus(str, PyEnum):
    """
    Заявка на вывод.

        pending ──«Выплатить» в админке──> sending ──перевод найден в сети──> completed
           │                                  │
           │                                  └──«перевод не прошёл»──> pending
           ├──«Отметить выплаченным» (перевод сделан вручную)──> completed
           └──«Отклонить»──> rejected (деньги вернулись на баланс)
    """
    PENDING = "pending"
    # Админ подписал перевод в кошельке площадки, ждём его в блокчейне
    SENDING = "sending"
    COMPLETED = "completed"
    REJECTED = "rejected"


class Withdrawal(Base):
    __tablename__ = "withdrawals"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # User who requested withdrawal
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    
    # Withdrawal details
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    wallet: Mapped[str] = mapped_column(String(255), nullable=False)

    # Валюта вывода. До этого поля выводы были только в USD (реферальные), а
    # заработок продавца копится в TON и вывести его было нечем.
    currency: Mapped[str] = mapped_column(
        String(10), default="USD", server_default=text("'USD'"), nullable=False
    )
    # Целочисленная сумма (см. services/money.py). Поле amount типа Float
    # оставлено: на него опирается существующий API и старые записи, но
    # считать по нему деньги нельзя.
    amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    
    # Status
    status: Mapped[WithdrawalStatus] = mapped_column(
        Enum(WithdrawalStatus, native_enum=False, length=20),
        default=WithdrawalStatus.PENDING,
        nullable=False
    )
    
    # Выплата через TonConnect из админки. Комментарий перевода уникален на
    # заявку: по нему перевод находится в блокчейне и заявка закрывается сама
    payout_comment: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Почему отклонена — человек видит это в истории выводов
    reject_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    user: Mapped["User"] = relationship("User", backref="withdrawals")
    
    def __repr__(self) -> str:
        return f"<Withdrawal(id={self.id}, user_id={self.user_id}, status={self.status}, amount={self.amount})>"
