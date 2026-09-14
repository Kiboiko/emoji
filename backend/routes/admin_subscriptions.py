"""Админка подписок: модерация каналов, список подписок, ручная выдача и отзыв."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models.subscription import (
    Channel, ChannelStatus, Subscription, SubscriptionAccessLog,
    SubscriptionStatus,
)
from models.user import User
from services import subscription_service
from utils.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/subscriptions", tags=["Admin Subscriptions"])


class ModerationDecision(BaseModel):
    approve: bool
    comment: Optional[str] = None


@router.get("/channels")
async def list_channels(
    status: Optional[ChannelStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Channel).options(
        selectinload(Channel.owner), selectinload(Channel.plans)
    )
    if status:
        stmt = stmt.where(Channel.status == status)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    channels = (
        await db.execute(stmt.order_by(Channel.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    # Число активных подписчиков одним запросом, а не по каналу в цикле
    counts = dict(
        (
            await db.execute(
                select(Subscription.channel_id, func.count())
                .where(Subscription.status == SubscriptionStatus.ACTIVE)
                .group_by(Subscription.channel_id)
            )
        ).all()
    )

    return {
        "items": [
            {
                "id": str(c.id),
                "title": c.title,
                "username": c.username,
                "telegram_chat_id": c.telegram_chat_id,
                "status": c.status.value,
                "bot_is_admin": c.bot_is_admin,
                "bot_check_error": c.bot_check_error,
                "bot_checked_at": c.bot_checked_at.isoformat() if c.bot_checked_at else None,
                "payout_wallet": c.payout_wallet,
                "owner_username": c.owner.username if c.owner else None,
                "owner_telegram_id": c.owner.telegram_id if c.owner else None,
                "plans_count": len(c.plans),
                "active_subscribers": counts.get(c.id, 0),
                "created_at": c.created_at.isoformat(),
            }
            for c in channels
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.post("/channels/{channel_id}/moderate")
async def moderate_channel(
    channel_id: uuid.UUID,
    decision: ModerationDecision,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Одобряет или отклоняет канал.

    Перед одобрением права бота проверяются заново: между подачей заявки и
    решением модератора автор мог разжаловать бота, и тогда подписки
    продавались бы на канал, доступ в который выдать невозможно.
    """
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    if decision.approve:
        ok, error = await subscription_service.verify_channel(db, channel)
        if not ok:
            await db.commit()
            raise HTTPException(
                status_code=400,
                detail=f"Нельзя опубликовать: {error}. Права бота проверены только что.",
            )
        channel.status = ChannelStatus.ACTIVE
    else:
        channel.status = ChannelStatus.REJECTED

    channel.moderation_comment = decision.comment
    channel.moderated_at = datetime.utcnow()
    await db.commit()

    return {"status": channel.status.value}


@router.post("/channels/{channel_id}/suspend")
async def suspend_channel(
    channel_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel.status = ChannelStatus.SUSPENDED
    channel.moderated_at = datetime.utcnow()
    await db.commit()
    return {"status": channel.status.value}


@router.get("")
async def list_subscriptions(
    channel_id: Optional[uuid.UUID] = Query(None),
    status: Optional[SubscriptionStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Subscription).options(
        selectinload(Subscription.user),
        selectinload(Subscription.channel),
        selectinload(Subscription.plan),
    )
    if channel_id:
        stmt = stmt.where(Subscription.channel_id == channel_id)
    if status:
        stmt = stmt.where(Subscription.status == status)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await db.execute(stmt.order_by(Subscription.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(s.id),
                "user_username": s.user.username if s.user else None,
                "user_telegram_id": s.user.telegram_id if s.user else None,
                "channel_title": s.channel.title if s.channel else None,
                "plan_title": s.plan.title_ru if s.plan else None,
                "status": s.status.value,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "joined": s.joined_at is not None,
            }
            for s in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/{subscription_id}/log")
async def subscription_log(
    subscription_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Журнал выдачи и отзыва доступа — для разбора «почему у меня нет доступа»."""
    rows = (
        await db.execute(
            select(SubscriptionAccessLog)
            .where(SubscriptionAccessLog.subscription_id == subscription_id)
            .order_by(SubscriptionAccessLog.created_at.desc())
        )
    ).scalars().all()

    return [
        {
            "action": r.action.value,
            "detail": r.detail,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/{subscription_id}/revoke")
async def revoke_subscription(
    subscription_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Ручной отзыв доступа: возврат средств, нарушение правил."""
    subscription = (
        await db.execute(
            select(Subscription)
            .options(selectinload(Subscription.channel), selectinload(Subscription.user))
            .where(Subscription.id == subscription_id)
        )
    ).scalars().first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    ok = await subscription_service.revoke_access(
        db, subscription,
        status=SubscriptionStatus.REVOKED,
        reason=f"отозвано администратором {admin.username or admin.id}",
    )
    await db.commit()
    return {"status": subscription.status.value, "telegram_ok": ok}


@router.post("/{subscription_id}/reissue-invite")
async def admin_reissue_invite(
    subscription_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Ручная выдача ссылки, если автоматическая не удалась."""
    subscription = (
        await db.execute(
            select(Subscription)
            .options(selectinload(Subscription.channel))
            .where(Subscription.id == subscription_id)
        )
    ).scalars().first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    link = await subscription_service.issue_invite(db, subscription)
    await db.commit()
    if not link:
        raise HTTPException(status_code=503, detail="Telegram отклонил создание ссылки")
    return {"invite_link": link}
