import uuid
from datetime import datetime
from sqlalchemy import String, BigInteger, Boolean, DateTime, ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class User(Base):
    __tablename__ = "users"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    language_code: Mapped[str] = mapped_column(String(10), default="ru", nullable=False)
    
    # Admin
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String, nullable=True)

    # Moderation. Колонка существует в БД с первой миграции, но отсутствовала в модели —
    # из-за этого INSERT не заполнял её и регистрация новых пользователей падала
    # с NotNullViolationError. server_default нужен для уже существующих строк.
    is_blocked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    
    # Referral system
    referrer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    referral_code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    referral_earnings: Mapped[float] = mapped_column(default=0.0, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Когда человек последний раз открыл или свернул приложение — «был(а) в
    # сети» в чате сделки. «В сети» сейчас знает менеджер сокетов, а не база
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    referrer: Mapped["User | None"] = relationship(
        "User",
        remote_side=[id],
        back_populates="referrals",
        foreign_keys=[referrer_id]
    )
    referrals: Mapped[list["User"]] = relationship(
        "User",
        back_populates="referrer",
        foreign_keys=[referrer_id]
    )
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    cart_items: Mapped[list["CartItem"]] = relationship("CartItem", back_populates="user", cascade="all, delete-orphan")
    reviews: Mapped[list["Review"]] = relationship("Review", back_populates="user", cascade="all, delete-orphan")
    referral_transactions_as_referrer: Mapped[list["ReferralTransaction"]] = relationship(
        "ReferralTransaction",
        foreign_keys="ReferralTransaction.referrer_id",
        back_populates="referrer",
        cascade="all, delete-orphan"
    )
    referral_transactions_as_referral: Mapped[list["ReferralTransaction"]] = relationship(
        "ReferralTransaction",
        foreign_keys="ReferralTransaction.referral_id",
        back_populates="referral",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username={self.username})>"
