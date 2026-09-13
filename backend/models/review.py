import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, Boolean, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # User who wrote the review (nullable for fake reviews)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True
    )

    # Product being reviewed
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False
    )

    # Order (nullable for fake reviews)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=True
    )

    # Review content
    text: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Optional rating 1-5

    # Telegram channel message ID
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Admin moderation
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Fake review fields
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fake_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fake_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="reviews")
    product: Mapped["Product"] = relationship("Product", back_populates="reviews")
    order: Mapped["Order"] = relationship("Order", back_populates="reviews")
    
    def __repr__(self) -> str:
        return f"<Review(id={self.id}, user_id={self.user_id}, product_id={self.product_id})>"
