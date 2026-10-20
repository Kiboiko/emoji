"""
Журнал действий персонала и журнал входов в админку.

log_action пишет в сессию вызывающего БЕЗ коммита: запись и само действие
фиксируются одной транзакцией — действие без записи и запись без действия
невозможны. Если действие откатится, откатится и запись о нём.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.admin_log import AdminAuditLog, AdminLoginLog
from models.user import User

logger = logging.getLogger(__name__)


def role_of(user: User | None) -> str:
    if user is None:
        return "system"
    if user.is_admin:
        return "admin"
    if user.is_moderator:
        return "moderator"
    return "system"


def log_action(
    db: AsyncSession,
    actor: User | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: Any = None,
    details: dict | None = None,
) -> AdminAuditLog:
    """
    Записывает действие. Коммит остаётся за вызывающим.

    actor пустой — действие системы без человека (например, автопубликация
    проверенного продавца).
    """
    entry = AdminAuditLog(
        id=uuid.uuid4(),
        actor_id=actor.id if actor is not None else None,
        actor_name=(actor.username or actor.first_name or "?")[:100] if actor is not None else "система",
        actor_role=role_of(actor),
        action=action,
        target_type=target_type,
        target_id=str(target_id)[:64] if target_id is not None else None,
        details=details or None,
    )
    db.add(entry)
    return entry


def log_login(
    db: AsyncSession,
    *,
    username: str,
    success: bool,
    reason: str,
    ip: str | None,
    user_agent: str | None,
    user: User | None = None,
) -> AdminLoginLog:
    """Запись о попытке входа. Пароль не сохраняется никогда."""
    entry = AdminLoginLog(
        id=uuid.uuid4(),
        user_id=user.id if user is not None else None,
        username=(username or "")[:100],
        success=success,
        reason=reason,
        ip=(ip or "")[:64] or None,
        user_agent=(user_agent or "")[:300] or None,
    )
    db.add(entry)
    return entry
