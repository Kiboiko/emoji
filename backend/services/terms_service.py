"""
Условия использования площадки: текст, версии, фиксация согласий.

Согласие запрашивается один раз на версию, а не перед каждой покупкой:
галочка на каждом заказе приучает щёлкать не читая, и юридически такое
согласие стоит меньше. Если текст условий меняется, владелец повышает
terms_version — и все пользователи принимают новую редакцию заново.

Записи согласий хранят telegram_id отдельно от user_id: доказательство
согласия должно пережить удаление аккаунта.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.p2p import TermsAcceptance
from models.user import User
from services import settings_service


class TermsNotAccepted(Exception):
    """Пользователь не принял текущую редакцию условий."""

    def __init__(self, version: str):
        self.version = version
        super().__init__(f"Необходимо принять условия площадки (редакция {version})")


async def current(db: AsyncSession) -> tuple[str, str]:
    """(версия, текст) текущей редакции."""
    version = await settings_service.get_str(db, "terms_version")
    text = await settings_service.get_str(db, "terms_text")
    return version, text


async def has_accepted(db: AsyncSession, user: User, version: str | None = None) -> bool:
    if version is None:
        version, _ = await current(db)
    found = (
        await db.execute(
            select(TermsAcceptance.id).where(
                TermsAcceptance.user_id == user.id,
                TermsAcceptance.terms_version == version,
            ).limit(1)
        )
    ).scalar_one_or_none()
    return found is not None


async def record(
    db: AsyncSession,
    user: User,
    *,
    context: str,
    ref_type: str | None = None,
    ref_id: uuid.UUID | None = None,
) -> str:
    """Фиксирует согласие с текущей редакцией. Возвращает её версию."""
    version, _ = await current(db)
    db.add(TermsAcceptance(
        id=uuid.uuid4(),
        user_id=user.id,
        telegram_id=user.telegram_id,
        terms_version=version,
        context=context,
        ref_type=ref_type,
        ref_id=ref_id,
    ))
    return version


async def require(
    db: AsyncSession,
    user: User,
    *,
    accepted_now: bool,
    context: str,
    ref_type: str | None = None,
    ref_id: uuid.UUID | None = None,
) -> None:
    """
    Пропускает дальше, только если условия приняты.

    Либо пользователь уже принимал текущую редакцию раньше, либо ставит
    галочку прямо сейчас (accepted_now) — тогда согласие фиксируется.
    """
    version, _ = await current(db)
    if await has_accepted(db, user, version):
        return
    if not accepted_now:
        raise TermsNotAccepted(version)
    await record(db, user, context=context, ref_type=ref_type, ref_id=ref_id)
