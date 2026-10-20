"""Условия использования площадки."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services import terms_service
from utils.auth import get_current_user

router = APIRouter(prefix="/api/terms", tags=["Terms"])


class AcceptIn(BaseModel):
    # Версия, которую пользователь видел на экране. Если к моменту нажатия
    # владелец успел обновить текст, согласие со старой редакцией не должно
    # засчитаться как согласие с новой.
    version: str


@router.get("")
async def get_terms(lang: str = Query("ru"), db: AsyncSession = Depends(get_db)):
    """
    Текущая редакция условий. Публичный: читать можно до регистрации.

    lang — язык приложения. Нет перевода — придёт русский текст, поле
    language в ответе говорит, на каком языке текст на самом деле.
    """
    wanted = "en" if lang == "en" else "ru"
    version, text = await terms_service.current(db, wanted)
    served = wanted
    if wanted == "en" and text == (await terms_service.current(db, "ru"))[1]:
        served = "ru"     # перевода нет — отдан русский текст
    return {
        "version": version,
        "text": text,
        "language": served,
        "is_empty": not text.strip(),
    }


@router.get("/status")
async def terms_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Нужно ли показывать пользователю галочку перед покупкой."""
    version, _ = await terms_service.current(db)
    return {
        "version": version,
        "accepted": await terms_service.has_accepted(db, user, version),
    }


@router.post("/accept")
async def accept_terms(
    payload: AcceptIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    version, _ = await terms_service.current(db)
    if payload.version != version:
        return {
            "accepted": False,
            "version": version,
            "message": "Условия обновились, пока страница была открыта. Ознакомьтесь с новой редакцией.",
        }

    if not await terms_service.has_accepted(db, user, version):
        await terms_service.record(db, user, context="page")
        await db.commit()

    return {"accepted": True, "version": version}
