"""Paid promotion invoices are separate from product purchase/escrow payments."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ProductPromotion(Base):
    __tablename__ = "product_promotions"

    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    promoted_until: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class PromotionInvoice(Base):
    __tablename__ = "promotion_invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Preserve paid invoices if a product is deleted; refund remains attributable.
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    amount_nano: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    network: Mapped[str] = mapped_column(String(10), nullable=False)
    destination_address: Mapped[str] = mapped_column(String(80), nullable=False)
    payment_comment: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(String(128), unique=True)
    received_nano: Mapped[int | None] = mapped_column(BigInteger)
    credited_nano: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    credit_reason: Mapped[str | None] = mapped_column(String(24))
    seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    promoted_until: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint("amount_nano > 0 AND duration_hours > 0", name="ck_promotion_invoice_positive"),
        Index("ix_promotion_invoices_status_expires", "status", "expires_at"),
        Index("ix_promotion_invoices_product", "product_id"),
    )
