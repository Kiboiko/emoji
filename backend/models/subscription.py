import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, Integer, Numeric,
    String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ChannelStatus(str, PyEnum):
    DRAFT = "draft"            # автор заполняет
    PENDING = "pending"        # ждёт модерации
    ACTIVE = "active"          # опубликован, подписки продаются
    SUSPENDED = "suspended"    # снят администрацией
    REJECTED = "rejected"


class SubscriptionStatus(str, PyEnum):
    PENDING = "pending"        # оплачен, доступ ещё не выдан
    ACTIVE = "active"
    EXPIRED = "expired"        # срок вышел, доступ отозван
    REVOKED = "revoked"        # отозван вручную (возврат, нарушение)


class AccessAction(str, PyEnum):
    """Журнал выдачи и отзыва доступа — нужен для разбора спорных ситуаций."""
    INVITE_CREATED = "invite_created"
    JOINED = "joined"
    LEFT = "left"
    KICKED = "kicked"
    KICK_FAILED = "kick_failed"
    INVITE_FAILED = "invite_failed"
    REVOKED = "revoked"
    EXTENDED = "extended"
    # Снятие бана перед выдачей доступа. «Удалить участника» через интерфейс
    # Telegram — это бан, и забаненный не войдёт ни по какой ссылке.
    RESTORED = "restored"


class Channel(Base):
    """
    Закрытый канал автора, доступ в который продаётся по подписке.

    bot_is_admin — не украшение: без прав администратора бот физически не может
    ни создать инвайт, ни удалить пользователя по истечении подписки. Поэтому
    канал без подтверждённых прав нельзя перевести в ACTIVE.
    """
    __tablename__ = "channels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    # Название из Telegram — обновляется при каждой проверке прав бота
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Название, которое автор задал сам, на двух языках. Главнее
    # телеграмного: его не перезаписывает проверка прав бота
    title_ru: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Описание для английского интерфейса: в каталоге подписка показывается
    # обычным товаром, и её описание берётся отсюда
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Обложка подписок — картинка, которую автор загрузил сам. Отдельно от
    # аватара: тот подтягивается из Telegram при каждой проверке прав бота и
    # затёр бы загруженное. При показе обложка главнее — её выбрали руками.
    cover_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Кошелёк автора для выплат. Заполняется при подключении канала.
    payout_wallet: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Галочка проверенного автора — см. SellerProfile.is_verified
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    bot_is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    bot_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bot_check_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[ChannelStatus] = mapped_column(
        Enum(ChannelStatus, native_enum=False, length=20),
        default=ChannelStatus.DRAFT, nullable=False,
    )
    moderation_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Версия условий площадки, принятая автором при подключении канала
    terms_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    owner: Mapped["User"] = relationship("User")
    plans: Mapped[list["SubscriptionPlan"]] = relationship(
        "SubscriptionPlan", back_populates="channel", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="channel", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_channels_status", "status"),)

    def display_title(self, language: str = "ru") -> str:
        """Название в интерфейсе: заданное автором, а если его нет — из Telegram."""
        if language == "en":
            return self.title_en or self.title_ru or self.title
        return self.title_ru or self.title

    def __repr__(self) -> str:
        return f"<Channel({self.title}, chat_id={self.telegram_chat_id}, {self.status.value})>"


class SubscriptionPlan(Base):
    """
    Тариф: срок и цена доступа в канал.

    Привязан к товару (Product с type='subscription'), чтобы подписка
    продавалась через ту же корзину, заказ и оплату, что и остальные товары.
    Создавать отдельный путь покупки ради подписок не нужно — существующий
    уже протестирован.
    """
    __tablename__ = "subscription_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    # Товар-витрина. SET NULL, а не CASCADE: удаление товара из каталога не
    # должно уносить тариф вместе с историей подписок по нему.
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )

    title_ru: Mapped[str] = mapped_column(String(255), nullable=False)
    title_en: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    price_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    channel: Mapped["Channel"] = relationship("Channel", back_populates="plans")
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="plan"
    )

    def __repr__(self) -> str:
        return f"<SubscriptionPlan({self.title_ru}, {self.duration_days}д, ${self.price_usd})>"


class Subscription(Base):
    """
    Подписка пользователя на канал.

    Уникальность (user_id, channel_id) НЕ ставится: у пользователя может быть
    несколько записей по одному каналу за историю (подписался, истёк,
    подписался снова). Активная при этом одна — за этим следит сервис,
    продлевая существующую вместо создания второй.
    """
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_plans.id", ondelete="SET NULL"), nullable=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, native_enum=False, length=20),
        default=SubscriptionStatus.PENDING, nullable=False,
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    invite_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invite_link_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Чтобы не слать одно и то же напоминание каждый прогон джобы
    reminder_sent_for_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped["User"] = relationship("User")
    channel: Mapped["Channel"] = relationship("Channel", back_populates="subscriptions")
    plan: Mapped["SubscriptionPlan | None"] = relationship(
        "SubscriptionPlan", back_populates="subscriptions"
    )
    access_log: Mapped[list["SubscriptionAccessLog"]] = relationship(
        "SubscriptionAccessLog", back_populates="subscription", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Основной запрос джобы истечения: "активные, у которых срок вышел"
        Index("ix_subscriptions_status_expires", "status", "expires_at"),
        Index("ix_subscriptions_user_channel", "user_id", "channel_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Subscription(user={self.user_id}, channel={self.channel_id}, "
            f"{self.status.value}, до {self.expires_at})>"
        )


class SubscriptionAccessLog(Base):
    """
    Журнал действий с доступом.

    Telegram может отказать по множеству причин (бота разжаловали, канал
    удалён, пользователь заблокировал бота). Без журнала разобраться, почему
    у конкретного человека нет доступа, невозможно.
    """
    __tablename__ = "subscription_access_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[AccessAction] = mapped_column(
        Enum(AccessAction, native_enum=False, length=20), nullable=False
    )
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    subscription: Mapped["Subscription"] = relationship(
        "Subscription", back_populates="access_log"
    )

    __table_args__ = (Index("ix_access_log_subscription", "subscription_id", "created_at"),)
