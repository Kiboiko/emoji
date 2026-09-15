import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, Integer, Numeric, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class Product(Base):
    __tablename__ = "products"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Bilingual content
    name_ru: Mapped[str] = mapped_column(String(500), nullable=False)
    name_en: Mapped[str] = mapped_column(String(500), nullable=False)
    description_ru: Mapped[str] = mapped_column(Text, nullable=False)
    description_en: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Pricing
    price_usdt: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    price_ton: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    
    # Media
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    
    # Category
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False
    )
    
    # Display settings
    is_top: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Stock (optional)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # Product type and quantity limits
    type: Mapped[str] = mapped_column(String(50), default="digital", nullable=False)
    min_quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Content to deliver after purchase (keys, files, instructions)
    content_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    
    # --- P2P: товар пользователя, а не площадки -------------------------
    # NULL в owner_user_id = товар платформы. По этому полю витрина рисует
    # пометку «товар пользователя», а оплата уходит в escrow вместо прямой
    # выдачи.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_p2p: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    category: Mapped["Category"] = relationship("Category", back_populates="products")
    order_items: Mapped[list["OrderItem"]] = relationship("OrderItem", back_populates="product")
    cart_items: Mapped[list["CartItem"]] = relationship("CartItem", back_populates="product", cascade="all, delete-orphan")
    reviews: Mapped[list["Review"]] = relationship("Review", back_populates="product", cascade="all, delete-orphan")
    digital_items: Mapped[list["DigitalItem"]] = relationship("DigitalItem", back_populates="product", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<Product(id={self.id}, name_ru={self.name_ru}, price_usdt={self.price_usdt})>"
