import uuid
from datetime import datetime
from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

class DigitalItem(Base):
    __tablename__ = "digital_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    
    # The actual content (e.g. login:pass, key, link)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Status
    is_sold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Reservation logic
    # When a user creates an order (pending), we set order_id and reserved_until.
    # If sold, order_id remains properly linked.
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    reserved_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="digital_items")
