"""
Внутренний API для бота.

Бот живёт отдельным контейнером и апдейты Telegram получает только он: события
входа и выхода из канала (chat_member) до бэкенда иначе не доходят. Поэтому
бот пересылает их сюда.

Эндпоинты закрыты общим секретом INTERNAL_API_TOKEN и не должны быть доступны
снаружи: в nginx путь /api/internal/ наружу не проксируется.
"""

from __future__ import annotations

import hmac
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.subscription import (
    AccessAction, Channel, Subscription, SubscriptionAccessLog, SubscriptionStatus,
)
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal", tags=["Internal"])


async def require_internal_token(
    x_internal_token: str = Header(..., alias="X-Internal-Token"),
) -> None:
    if not settings.INTERNAL_API_TOKEN:
        # Пустой секрет не должен означать «пускать всех»
        raise HTTPException(status_code=503, detail="Internal API is not configured")
    if not hmac.compare_digest(x_internal_token, settings.INTERNAL_API_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid internal token")


class ChatMemberEvent(BaseModel):
    chat_id: int
    telegram_user_id: int
    # "member" — вошёл, "left"/"kicked" — вышел или удалён
    new_status: str


@router.post("/chat-member", dependencies=[Depends(require_internal_token)])
async def handle_chat_member(
    event: ChatMemberEvent,
    db: AsyncSession = Depends(get_db),
):
    """
    Фиксирует вход и выход участника закрытого канала.

    Зачем: без этого нельзя отличить «купил подписку, но так и не перешёл по
    ссылке» от «пользуется каналом», а при разборе жалоб непонятно, был ли
    доступ вообще.
    """
    channel = (
        await db.execute(select(Channel).where(Channel.telegram_chat_id == event.chat_id))
    ).scalars().first()
    if channel is None:
        return {"ignored": "unknown channel"}

    user = (
        await db.execute(select(User).where(User.telegram_id == event.telegram_user_id))
    ).scalars().first()
    if user is None:
        return {"ignored": "unknown user"}

    subscription = (
        await db.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user.id,
                Subscription.channel_id == channel.id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
            .order_by(Subscription.created_at.desc())
        )
    ).scalars().first()
    if subscription is None:
        return {"ignored": "no active subscription"}

    joined = event.new_status in ("member", "administrator", "creator", "restricted")

    if joined:
        if subscription.joined_at is None:
            subscription.joined_at = datetime.utcnow()
        # Ссылка одноразовая и уже использована
        subscription.invite_link = None
        action = AccessAction.JOINED
    else:
        action = AccessAction.LEFT

    db.add(SubscriptionAccessLog(
        subscription_id=subscription.id,
        action=action,
        detail={"telegram_status": event.new_status},
    ))
    await db.commit()

    logger.info(
        "[INTERNAL] chat_member: %s -> %s в канале %s",
        event.telegram_user_id, event.new_status, channel.title,
    )
    return {"ok": True, "subscription_id": str(subscription.id), "action": action.value}
