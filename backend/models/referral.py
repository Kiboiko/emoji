import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class ReferralTransaction(Base):
    __tablename__ = "referral_transactions"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Referrer (who gets the commission)
    referrer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    
    # Referral (who made the purchase)
    referral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    
    # Order that triggered the commission
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False
    )
    
    # Commission amount (3% of order total)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # --- Настраиваемая программа (этап 6) --------------------------------
    # Уровень: 1 — прямой реферер, 2 — реферер реферера.
    level: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )

    # Процент, применённый в момент начисления. Хранится вместе с транзакцией,
    # потому что настройка меняется: без снимка нельзя объяснить, откуда
    # взялась сумма в старой выплате.
    #
    # NULL у начислений, сделанных до этапа 6: там процент был зашит в .env,
    # и подставлять его задним числом значило бы выдумывать данные.
    percent_bp_applied: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # product | subscription | p2p — с чего начислено. NULL у старых записей.
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Целочисленная сумма (см. services/money.py). Numeric-поле amount
    # оставлено: на него опирается существующий API и старые записи.
    amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(
        String(10), default="USD", server_default=text("'USD'"), nullable=False
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        # Главные запросы админки: история по рефереру и лента по дате
        Index("ix_referral_tx_referrer", "referrer_id", "created_at"),
        Index("ix_referral_tx_created", "created_at"),
    )

    # Relationships
    referrer: Mapped["User"] = relationship(
        "User",
        foreign_keys=[referrer_id],
        back_populates="referral_transactions_as_referrer"
    )
    referral: Mapped["User"] = relationship(
        "User",
        foreign_keys=[referral_id],
        back_populates="referral_transactions_as_referral"
    )
    order: Mapped["Order"] = relationship("Order", back_populates="referral_transactions")
    
    def __repr__(self) -> str:
        return f"<ReferralTransaction(id={self.id}, referrer_id={self.referrer_id}, amount={self.amount})>"
