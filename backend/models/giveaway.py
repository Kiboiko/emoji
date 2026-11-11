import uuid
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class Giveaway(Base):
    __tablename__ = "giveaways"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title_ru: Mapped[str] = mapped_column(String(200), nullable=False)
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    description_ru: Mapped[str] = mapped_column(Text, default="", nullable=False)
    description_en: Mapped[str] = mapped_column(Text, default="", nullable=False)
    prize: Mapped[str] = mapped_column(String(500), nullable=False)
    photo_url: Mapped[str | None] = mapped_column(String(500))
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    winner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    public_winner_label: Mapped[str | None] = mapped_column(String(60))
    public_winner_username: Mapped[str | None] = mapped_column(String(64))
    post_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    post_message_id: Mapped[int | None] = mapped_column(BigInteger)
    post_status: Mapped[str] = mapped_column(String(20), default="disabled", server_default="disabled", nullable=False)
    post_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    snapshot_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    fulfillment_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    draw_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    error_code: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (CheckConstraint("end_at > start_at", name="ck_giveaway_dates"),)


class GiveawayChat(Base):
    __tablename__ = "giveaway_required_chats"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    giveaway_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("giveaways.id", ondelete="RESTRICT"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    join_link: Mapped[str] = mapped_column(String(500), nullable=False)
    __table_args__ = (UniqueConstraint("giveaway_id", "chat_id"),)


class GiveawayEntry(Base):
    __tablename__ = "giveaway_entries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    giveaway_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("giveaways.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), default="checking", nullable=False)
    entered_at: Mapped[datetime | None] = mapped_column(DateTime)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_code: Mapped[str | None] = mapped_column(String(50))
    eligibility_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    __table_args__ = (UniqueConstraint("giveaway_id", "user_id"),)


class GiveawayDrawAttempt(Base):
    __tablename__ = "giveaway_draw_attempts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    giveaway_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("giveaways.id", ondelete="RESTRICT"), index=True)
    entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("giveaway_entries.id", ondelete="RESTRICT"))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="selected", nullable=False)
    selected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("giveaway_id", "entry_id"), UniqueConstraint("giveaway_id", "ordinal"))


class GiveawayPostCleanup(Base):
    """Only delivery coordinates survive deletion; no giveaway or user data."""
    __tablename__ = "giveaway_post_cleanup"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    has_photo: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    __table_args__ = (UniqueConstraint("chat_id", "message_id"),)
