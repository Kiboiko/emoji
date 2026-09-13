import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import String, DateTime, ForeignKey, Float, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class WithdrawalStatus(str, PyEnum):
    """Withdrawal status enumeration"""
    PENDING = "pending"
    COMPLETED = "completed"


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
    
    # Status
    status: Mapped[WithdrawalStatus] = mapped_column(
        Enum(WithdrawalStatus, native_enum=False, length=20),
        default=WithdrawalStatus.PENDING,
        nullable=False
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    user: Mapped["User"] = relationship("User", backref="withdrawals")
    
    def __repr__(self) -> str:
        return f"<Withdrawal(id={self.id}, user_id={self.user_id}, status={self.status}, amount={self.amount})>"
