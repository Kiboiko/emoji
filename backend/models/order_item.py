import uuid
from decimal import Decimal
from sqlalchemy import ForeignKey, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class OrderItem(Base):
    __tablename__ = "order_items"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Order
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False
    )
    
    # Product
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False
    )
    
    # Quantity and price at purchase time
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    price_usdt: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    price_ton: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    
    # Product snapshot (name, description, content_data at purchase time)
    product_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    
    # User provided data (e.g. service link)
    user_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    
    # Relationships
    order: Mapped["Order"] = relationship("Order", back_populates="items")
    product: Mapped["Product"] = relationship("Product", back_populates="order_items")
    
    def __repr__(self) -> str:
        return f"<OrderItem(id={self.id}, order_id={self.order_id}, product_id={self.product_id}, quantity={self.quantity})>"
