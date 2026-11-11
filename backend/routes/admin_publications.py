from datetime import datetime
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models.user import User
from models.telegram_publication import TelegramPublication
from services import telegram_publication_service as service, audit_service
from utils.auth import require_admin

router = APIRouter(prefix="/api/admin/publications", tags=["Admin publications"])


def config_view(c):
    return {"enabled": c.enabled, "min_nano": str(c.min_nano),
        "min_gram": str(Decimal(c.min_nano) / Decimal(1_000_000_000)), "chat_id": str(c.chat_id) if c.chat_id else "",
        "thread_id": c.thread_id}


class ConfigIn(BaseModel):
    enabled: bool = False
    min_nano: int = Field(0, ge=0, le=9_000_000_000_000_000)
    chat_id: int | None = Field(None, ge=-9_000_000_000_000_000, le=9_000_000_000_000_000)
    thread_id: int | None = Field(None, ge=1, le=2_147_483_647)


@router.get("/config")
async def configuration(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return config_view(await service.configuration(db))


@router.put("/config")
async def save(body: ConfigIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if body.enabled:
        if not body.chat_id or body.min_nano <= 0:
            raise HTTPException(422, "Укажите чат и положительный порог")
        try:
            await service.preflight(body.chat_id)
        except Exception:
            raise HTTPException(400, "Не удалось подтвердить права бота в чате")
    c = await service.configuration(db)
    changed = c.chat_id != body.chat_id or c.thread_id != body.thread_id or c.enabled != body.enabled
    if changed:
        await db.execute(update(TelegramPublication).where(TelegramPublication.status.in_(["pending", "retry"]))
            .values(status="suppressed"))
        c.enabled_at = datetime.utcnow() if body.enabled else None
    c.enabled, c.min_nano, c.chat_id, c.thread_id = body.enabled, body.min_nano, body.chat_id, body.thread_id
    audit_service.log_action(db, admin, "publications.config", details={"enabled": c.enabled, "min_nano": str(c.min_nano)})
    await db.commit()
    return config_view(c)


@router.get("")
async def history(skip: int = Query(0, ge=0), admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(TelegramPublication).order_by(TelegramPublication.created_at.desc())
        .offset(skip).limit(50))).all()
    return [{"id": str(r.id), "status": r.status, "attempts": r.attempts, "error_code": r.error_code,
             "message_id": r.telegram_message_id, "created_at": r.created_at.isoformat()+"Z",
             "preview": r.payload.get("text", "")} for r in rows]


class Resolution(BaseModel):
    action: str
    message_id: int | None = Field(None, ge=1, le=2_147_483_647)


@router.post("/{publication_id}/resolve")
async def resolve(publication_id: UUID, body: Resolution, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(TelegramPublication).where(TelegramPublication.id == publication_id).with_for_update())
    if row is None:
        raise HTTPException(404, "Публикация не найдена")
    if row.status != "unknown" or body.action not in ("confirmed_sent", "confirmed_not_sent", "suppress"):
        raise HTTPException(409, "Решение доступно только для неопределённой доставки")
    if body.action == "confirmed_sent" and not body.message_id:
        raise HTTPException(422, "Укажите ID найденного сообщения")
    row.status = {"confirmed_sent":"sent", "confirmed_not_sent":"retry", "suppress":"suppressed"}[body.action]
    row.telegram_message_id = body.message_id
    row.next_attempt_at, row.lease_until = datetime.utcnow(), None
    if row.status == "sent":
        row.sent_at = datetime.utcnow()
    audit_service.log_action(db, admin, "publications.resolve", target_type="publication", target_id=row.id,
        details={"action": body.action, "message_id": body.message_id})
    await db.commit()
    return {"status": row.status}
