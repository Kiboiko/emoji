"""
Персонал админки: модераторы, журнал входов, журнал действий.

Всё здесь — только для администратора. Модератор не видит ни список коллег,
ни чужие входы: он работает с заявками и спорами, а журнал действий нужен
владельцу, чтобы проверять модераторов.
"""

from __future__ import annotations

import re
import secrets
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.admin_log import AdminAuditLog, AdminLoginLog
from models.user import User
from routes.admin_auth import validate_new_password
from services import audit_service
from utils.auth import generate_referral_code, get_password_hash, require_admin

router = APIRouter(prefix="/api/admin/staff", tags=["Admin Staff"])

_LOGIN_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


class ModeratorCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=1, max_length=200)
    display_name: Optional[str] = Field(None, max_length=100)


class PasswordReset(BaseModel):
    password: str = Field(..., min_length=1, max_length=200)


class ActiveToggle(BaseModel):
    active: bool


def _moderator_dict(user: User, last_login, actions: int) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.first_name,
        "active": not user.is_blocked,
        # В UTC с явной «Z»: без неё браузер прочёл бы время как местное
        "created_at": user.created_at.isoformat() + "Z",
        "last_login": last_login.isoformat() + "Z" if last_login else None,
        "actions": actions,
    }


async def _get_moderator(db: AsyncSession, moderator_id: uuid.UUID) -> User:
    user = await db.get(User, moderator_id)
    # Администратора через этот раздел не трогаем: сменить пароль или
    # заблокировать главного админа отсюда было бы лазейкой
    if user is None or not user.is_moderator or user.is_admin:
        raise HTTPException(status_code=404, detail="Модератор не найден")
    return user


# ---------------------------------------------------------------------------
# Модераторы
# ---------------------------------------------------------------------------

@router.get("/moderators")
async def list_moderators(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    users = (
        await db.execute(
            select(User).where(User.is_moderator.is_(True), User.is_admin.is_(False))
            .order_by(User.created_at)
        )
    ).scalars().all()
    ids = [u.id for u in users]

    logins = {}
    actions = {}
    if ids:
        logins = dict((await db.execute(
            select(AdminLoginLog.user_id, func.max(AdminLoginLog.created_at))
            .where(AdminLoginLog.user_id.in_(ids), AdminLoginLog.success.is_(True))
            .group_by(AdminLoginLog.user_id)
        )).all())
        actions = dict((await db.execute(
            select(AdminAuditLog.actor_id, func.count(AdminAuditLog.id))
            .where(AdminAuditLog.actor_id.in_(ids))
            .group_by(AdminAuditLog.actor_id)
        )).all())

    return [_moderator_dict(u, logins.get(u.id), actions.get(u.id, 0)) for u in users]


@router.post("/moderators")
async def create_moderator(
    payload: ModeratorCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Заводит модератора со своим логином и паролем.

    Это не пользователь Telegram: строка в users нужна, чтобы действия
    привязывались к человеку, а telegram_id у неё отрицательный служебный
    (поле уникально и обязательно, а настоящему Telegram-идентификатору
    взяться неоткуда).
    """
    username = payload.username.strip()
    if not _LOGIN_RE.fullmatch(username):
        raise HTTPException(
            status_code=400,
            detail="Логин — 3–32 символа: латиница, цифры, точка, дефис и подчёркивание",
        )
    if username.lower() == settings.ADMIN_USERNAME.lower():
        raise HTTPException(status_code=400, detail="Этот логин занят")

    # Логин не должен совпадать с @username ни одного пользователя: иначе
    # пользователь приложения мог бы выбрать себе такой ник и спутать вход
    taken = (
        await db.execute(
            select(User.id).where(func.lower(User.username) == username.lower()).limit(1)
        )
    ).scalars().first()
    if taken is not None:
        raise HTTPException(status_code=400, detail="Этот логин уже занят")

    validate_new_password(payload.password, username)

    telegram_id = -(secrets.randbelow(10**12) + 1_000_000)
    while (await db.execute(select(User.id).where(User.telegram_id == telegram_id))).first():
        telegram_id = -(secrets.randbelow(10**12) + 1_000_000)

    referral_code = generate_referral_code()
    while (await db.execute(select(User.id).where(User.referral_code == referral_code))).first():
        referral_code = generate_referral_code()

    user = User(
        id=uuid.uuid4(),
        telegram_id=telegram_id,
        username=username,
        first_name=(payload.display_name or username).strip() or username,
        language_code="ru",
        is_moderator=True,
        hashed_password=get_password_hash(payload.password),
        referral_code=referral_code,
    )
    db.add(user)
    audit_service.log_action(
        db, admin, "moderator.create", target_type="user", target_id=user.id,
        details={"username": username},
    )
    await db.commit()
    return _moderator_dict(user, None, 0)


@router.post("/moderators/{moderator_id}/password")
async def reset_moderator_password(
    moderator_id: uuid.UUID,
    payload: PasswordReset,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Новый пароль модератору. Его прежние сессии завершаются."""
    user = await _get_moderator(db, moderator_id)
    validate_new_password(payload.password, user.username)
    user.hashed_password = get_password_hash(payload.password)
    user.token_version = int(user.token_version or 0) + 1
    audit_service.log_action(
        db, admin, "moderator.password_reset", target_type="user", target_id=user.id,
        details={"username": user.username},
    )
    await db.commit()
    return {"message": "Пароль изменён, прежние сессии завершены"}


@router.post("/moderators/{moderator_id}/revoke")
async def revoke_moderator_sessions(
    moderator_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Сброс токенов модератора: ему придётся войти заново."""
    user = await _get_moderator(db, moderator_id)
    user.token_version = int(user.token_version or 0) + 1
    audit_service.log_action(
        db, admin, "moderator.sessions_reset", target_type="user", target_id=user.id,
        details={"username": user.username},
    )
    await db.commit()
    return {"message": "Сессии модератора завершены"}


@router.post("/moderators/{moderator_id}/active")
async def set_moderator_active(
    moderator_id: uuid.UUID,
    payload: ActiveToggle,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Приостановить или вернуть модератора, не удаляя его историю."""
    user = await _get_moderator(db, moderator_id)
    user.is_blocked = not payload.active
    if not payload.active:
        user.token_version = int(user.token_version or 0) + 1
    audit_service.log_action(
        db, admin, "moderator.activate" if payload.active else "moderator.suspend",
        target_type="user", target_id=user.id, details={"username": user.username},
    )
    await db.commit()
    return _moderator_dict(user, None, 0)


@router.delete("/moderators/{moderator_id}")
async def remove_moderator(
    moderator_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Снимает роль модератора.

    Учётка остаётся: на неё ссылаются решения по заявкам и журнал действий.
    Пароль стирается, токены перестают действовать.
    """
    user = await _get_moderator(db, moderator_id)
    user.is_moderator = False
    user.hashed_password = None
    user.token_version = int(user.token_version or 0) + 1
    audit_service.log_action(
        db, admin, "moderator.remove", target_type="user", target_id=user.id,
        details={"username": user.username},
    )
    await db.commit()
    return {"removed": True}


# ---------------------------------------------------------------------------
# Журналы
# ---------------------------------------------------------------------------

@router.get("/login-log")
async def login_log(
    success: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AdminLoginLog)
    if success is not None:
        stmt = stmt.where(AdminLoginLog.success.is_(success))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await db.execute(stmt.order_by(AdminLoginLog.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(r.id),
                "username": r.username,
                "success": r.success,
                "reason": r.reason,
                "ip": r.ip,
                "user_agent": r.user_agent,
                "created_at": r.created_at.isoformat() + "Z",
            }
            for r in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/audit-log")
async def audit_log(
    actor_id: Optional[uuid.UUID] = Query(None),
    role: Optional[str] = Query(None, pattern="^(admin|moderator|system)$"),
    action: Optional[str] = Query(None, max_length=60),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AdminAuditLog)
    if actor_id is not None:
        stmt = stmt.where(AdminAuditLog.actor_id == actor_id)
    if role:
        stmt = stmt.where(AdminAuditLog.actor_role == role)
    if action:
        # Префикс: «listing» покажет и одобрения, и отказы
        stmt = stmt.where(AdminAuditLog.action.like(f"{action}%"))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await db.execute(stmt.order_by(AdminAuditLog.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(r.id),
                "actor_id": str(r.actor_id) if r.actor_id else None,
                "actor_name": r.actor_name,
                "actor_role": r.actor_role,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "details": r.details,
                "created_at": r.created_at.isoformat() + "Z",
            }
            for r in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }
