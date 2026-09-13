import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Numeric
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
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
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
