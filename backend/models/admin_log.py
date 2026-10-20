import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AdminLoginLog(Base):
    """
    Журнал входов в админку: каждая попытка, удачная и нет.

    Неудачные пишутся и для несуществующих логинов — по ним видно перебор.
    Логин сохраняется как введён (обрезанный), пароль — никогда.
    """
    __tablename__ = "admin_login_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # SET NULL: удаление учётки не должно стирать след её входов
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Причина отказа или пометка: bad_password, unknown_user, rate_limited, no_access, ok
    reason: Mapped[str] = mapped_column(String(40), nullable=False, default="ok")
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (Index("ix_admin_login_log_created", "created_at"),)


class AdminAuditLog(Base):
    """
    Журнал действий персонала: что сделал администратор или модератор.

    Пишется в той же транзакции, что и само действие: действие без записи и
    запись без действия невозможны. actor_name хранится отдельно от связи —
    запись должна пережить удаление учётки.
    """
    __tablename__ = "admin_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # admin | moderator | system
    actor_role: Mapped[str] = mapped_column(String(20), nullable=False)
    # Например listing.approve, listing.reject, deal.resolve, photo.delete
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        Index("ix_admin_audit_created", "created_at"),
        Index("ix_admin_audit_actor", "actor_id", "created_at"),
    )
