import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from sqlalchemy import String, DateTime, ForeignKey, Numeric, Enum, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class OrderStatus(str, PyEnum):
    """Order status enumeration"""
    PENDING = "pending"  # Создан, ожидает оплаты
    PAID = "paid"  # Оплачен
    COMPLETED = "completed"  # Завершён (данные отправлены)
    CANCELLED = "cancelled"  # Отменён


class CurrencyType(str, PyEnum):
    """Payment currency enumeration"""
    USDT = "USDT"
    TON = "TON"


class Order(Base):
    __tablename__ = "orders"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # User
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    
    # Totals
    total_usdt: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total_ton: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[CurrencyType] = mapped_column(
        Enum(CurrencyType, native_enum=False, length=10),
        nullable=False
    )
    
    # Status
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, native_enum=False, length=20),
        default=OrderStatus.PENDING,
        nullable=False
    )
    
    # Устаревшее поле от CryptoBot. Не удаляем: в нём лежит история
    # платежей до перехода на TON Connect.
    cryptobot_invoice_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payment_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    referral_transactions: Mapped[list["ReferralTransaction"]] = relationship(
        "ReferralTransaction",
        back_populates="order",
        cascade="all, delete-orphan"
    )
    reviews: Mapped[list["Review"]] = relationship("Review", back_populates="order")
    payments: Mapped[list["Payment"]] = relationship(
        "Payment", back_populates="order", cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<Order(id={self.id}, user_id={self.user_id}, status={self.status}, total_usdt={self.total_usdt})>"


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
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True
    )
    
    # Snapshot data at time of purchase
    product_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False) # Name, description, image, etc.
    
    # Price and Quantity
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    price_usdt: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    price_ton: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    
    # Service data (link, login, etc)
    user_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    
    # Relationships
    order: Mapped["Order"] = relationship("Order", back_populates="items")
    product: Mapped["Product"] = relationship("Product", back_populates="order_items")
    
    def __repr__(self) -> str:
        return f"<OrderItem(id={self.id}, order_id={self.order_id}, product_id={self.product_id})>"
