import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class Inquiry(Base):
    __tablename__ = "seller_inquiries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    buyer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    seller_profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("seller_profiles.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    paid_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"))
    linked_deal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("deals.id", ondelete="SET NULL"))
    buyer_read_at: Mapped[datetime | None] = mapped_column(DateTime)
    seller_read_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (
        Index("uq_inquiry_unpaid_pair", "buyer_id", "seller_id", unique=True, postgresql_where=text("paid_order_id IS NULL")),
        Index("ix_inquiry_buyer_created", "buyer_id", "created_at"),
        Index("ix_inquiry_seller_created", "seller_id", "created_at"),
    )


class InquiryMessage(Base):
    __tablename__ = "seller_inquiry_messages"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inquiry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("seller_inquiries.id", ondelete="CASCADE"), nullable=False)
    sender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    photo_path: Mapped[str | None] = mapped_column(String(255))
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("inquiry_id", "sender_id", "client_id", name="uq_inquiry_message_client"),
        Index("ix_inquiry_messages_chat", "inquiry_id", "created_at"),
        Index("ix_inquiry_messages_sender", "sender_id", "created_at"),
    )


class InquiryMediaCleanup(Base):
    __tablename__ = "seller_inquiry_media_cleanup"
    inquiry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
