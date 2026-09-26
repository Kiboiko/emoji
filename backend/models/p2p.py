import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey, Identity, Index, Integer,
    Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class SellerStatus(str, PyEnum):
    ACTIVE = "active"
    RESTRICTED = "restricted"   # временное ограничение за отказы
    BANNED = "banned"


class ListingStatus(str, PyEnum):
    DRAFT = "draft"
    PENDING = "pending"          # на модерации
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"      # снята продавцом
    ARCHIVED = "archived"


class DealStatus(str, PyEnum):
    """
    Состояния сделки.

    Переходы описаны в services/deal_service.py. Ключевое: деньги лежат
    замороженными на счёте платформы с момента оплаты и до подтверждения
    получения — продавцу они не начислены.
    """
    CREATED = "created"                    # заказ создан, оплаты ещё нет
    PAID_ESCROW = "paid_escrow"            # оплачено, деньги заморожены
    CHAT_OPENED = "chat_opened"            # релей-чат открыт
    DELIVERED_CLAIMED = "delivered_claimed"  # продавец отметил отправку
    CONFIRMED = "confirmed"                # покупатель подтвердил получение
    RELEASED = "released"                  # деньги начислены продавцу
    DISPUTED = "disputed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class MessageDirection(str, PyEnum):
    BUYER_TO_SELLER = "buyer_to_seller"
    SELLER_TO_BUYER = "seller_to_buyer"
    SYSTEM = "system"


class SellerProfile(Base):
    """Профиль продавца. Заводится при первой заявке на размещение."""
    __tablename__ = "seller_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Пустой у магазина площадки: за ним не стоит человек. Уникальности это
    # не мешает — несколько NULL уникальному индексу в PostgreSQL не помеха.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        unique=True, nullable=True,
    )

    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    payout_wallet: Mapped[str] = mapped_column(String(80), nullable=False)

    # Витрина магазина: логотип и описание. Логотип продавец грузит сам —
    # аватар Telegram сделал бы магазин похожим на личный аккаунт.
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Магазин самой площадки. Товары к нему не подвешиваются через
    # owner_user_id: то поле означает «товар пользователя» и тянет за собой
    # escrow, блокировку продавца и выплаты. Площадка продаёт напрямую.
    is_platform: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    # Галочка проверенного продавца. Ставит только администратор: смысл её в
    # том, что площадка подтвердила личность, а не в том, что продавец сам
    # себя отметил.
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    status: Mapped[SellerStatus] = mapped_column(
        Enum(SellerStatus, native_enum=False, length=20),
        default=SellerStatus.ACTIVE, nullable=False,
    )
    restricted_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    restriction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Рейтинг считается по отзывам о завершённых сделках
    rating_sum: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    rating_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    deals_completed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)

    # Счётчик отказов ПОДРЯД: сбрасывается при первом одобрении.
    # Именно подряд, а не всего: продавец с сотней товаров и парой старых
    # отказов не должен быть ограничен навсегда.
    rejected_streak: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)

    terms_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped["User"] = relationship("User")
    listings: Mapped[list["ProductListing"]] = relationship(
        "ProductListing", back_populates="seller", cascade="all, delete-orphan"
    )

    @property
    def rating(self) -> float | None:
        if not self.rating_count:
            return None
        return round(self.rating_sum / self.rating_count, 2)

    def __repr__(self) -> str:
        return f"<SellerProfile({self.display_name}, {self.status.value})>"


class ProductListing(Base):
    """
    Заявка продавца на размещение товара.

    Отделена от Product намеренно: заявка живёт своей жизнью (черновик,
    модерация, отказ с причиной), а Product создаётся только после одобрения.
    Так отклонённые заявки не засоряют каталог и не требуют «скрытых» товаров.
    """
    __tablename__ = "product_listings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seller_profiles.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL: удаление товара из каталога не должно уносить историю заявки
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    # Английское название. Необязательное: если автор его не указал, при
    # публикации в обе колонки товара уходит русское — как было раньше.
    name_en: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Английское описание. Как и название, необязательное в базе: у заявок,
    # заведённых до его появления, текста нет, и подставлять туда русский
    # нельзя — потом не отличить «так и хотели» от «поля не было».
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    status: Mapped[ListingStatus] = mapped_column(
        Enum(ListingStatus, native_enum=False, length=20),
        default=ListingStatus.DRAFT, nullable=False,
    )
    moderator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    moderation_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    seller: Mapped["SellerProfile"] = relationship("SellerProfile", back_populates="listings")
    images: Mapped[list["ListingImage"]] = relationship(
        "ListingImage", back_populates="listing",
        cascade="all, delete-orphan", order_by="ListingImage.sort_order",
    )

    __table_args__ = (Index("ix_listings_status", "status", "created_at"),)

    def __repr__(self) -> str:
        return f"<ProductListing({self.name[:30]}, {self.status.value})>"


class ListingImage(Base):
    """
    Фото товара.

    Отдельная таблица, потому что у Product всего одна картинка
    (image_url: String) — для товаров площадки этого хватало, для
    пользовательских объявлений нужно несколько.
    """
    __tablename__ = "listing_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_listings.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    listing: Mapped["ProductListing"] = relationship("ProductListing", back_populates="images")


class Deal(Base):
    """
    Сделка между покупателем и продавцом.

    Одна сделка = одна позиция P2P-товара в заказе. Если покупатель взял
    товары двух разных продавцов, сделок будет две: у каждой свой чат, свой
    срок подтверждения и свой исход.
    """
    __tablename__ = "deals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Человекочитаемый номер для чата и поддержки: «Сделка №123».
    # Identity, а не autoincrement: в SQLAlchemy autoincrement действует только
    # на первичный ключ, а здесь первичный — id. Без последовательности колонка
    # оставалась бы NOT NULL без значения, и первая же сделка не создалась бы.
    number: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), unique=True, nullable=False
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    order_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_items.id", ondelete="SET NULL"), nullable=True
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    product_name: Mapped[str] = mapped_column(String(500), nullable=False)

    # Суммы в нанотонах, целые (см. services/money.py)
    amount_nano: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    commission_nano: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    seller_amount_nano: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    status: Mapped[DealStatus] = mapped_column(
        Enum(DealStatus, native_enum=False, length=20),
        default=DealStatus.CREATED, nullable=False,
    )

    # Дедлайн автоподтверждения: если покупатель молчит, сделка закрывается
    # сама, иначе деньги продавца зависали бы навсегда
    confirm_deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    dispute_opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dispute_opened_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    dispute_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Чат закрывается на запись после завершения, история остаётся читаемой
    chat_closed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    buyer: Mapped["User"] = relationship("User", foreign_keys=[buyer_id])
    seller: Mapped["User"] = relationship("User", foreign_keys=[seller_id])
    messages: Mapped[list["DealMessage"]] = relationship(
        "DealMessage", back_populates="deal", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Главный запрос джобы автоподтверждения
        Index("ix_deals_status_deadline", "status", "confirm_deadline_at"),
        Index("ix_deals_buyer", "buyer_id"),
        Index("ix_deals_seller", "seller_id"),
    )

    def __repr__(self) -> str:
        return f"<Deal(#{self.number}, {self.status.value}, {self.amount_nano} nano)>"


class DealMessage(Base):
    """
    Сообщение в релей-чате сделки.

    Бот пересылает сообщения между личками сторон через copyMessage — копия
    приходит без пометки «переслано от», поэтому стороны не видят профили друг
    друга. Здесь хранится всё, что прошло через релей: это единственное
    доказательство при разборе спора.

    Медиа храним как file_id Telegram, а не файлами: Telegram хостит их сам,
    а file_id остаётся валидным и позволяет админу переслать вложение себе.
    """
    __tablename__ = "deal_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deals.id", ondelete="CASCADE"), nullable=False
    )

    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, native_enum=False, length=20), nullable=False
    )
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # photo / document / voice / video / ...
    media_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # id исходного сообщения у отправителя и копии у получателя.
    # Копия нужна для маршрутизации: reply на неё определяет сделку.
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delivered_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    deal: Mapped["Deal"] = relationship("Deal", back_populates="messages")

    __table_args__ = (
        Index("ix_deal_messages_deal", "deal_id", "created_at"),
        # По этому индексу ищем сделку при reply на копию
        Index("ix_deal_messages_delivered", "delivered_message_id"),
    )


class TermsAcceptance(Base):
    """
    Фиксация согласия с условиями площадки.

    Хранится telegram_id, а не только ссылка на пользователя: запись должна
    пережить удаление аккаунта, иначе доказательства согласия исчезнут вместе
    с ним.
    """
    __tablename__ = "terms_acceptances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    terms_version: Mapped[str] = mapped_column(String(20), nullable=False)
    # purchase | listing | channel
    context: Mapped[str] = mapped_column(String(30), nullable=False)
    ref_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (Index("ix_terms_user_version", "user_id", "terms_version"),)
