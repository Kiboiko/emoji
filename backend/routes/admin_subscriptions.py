"""Админка подписок: модерация каналов, список подписок, ручная выдача и отзыв."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Literal
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from config import settings
from models.subscription import (
    Channel, ChannelStatus, Subscription, SubscriptionAccessLog,
    SubscriptionStatus,
)
from models.user import User
from models.product import Product
from models.p2p import ListingImage, SellerProfile
from services import subscription_service, audit_service, image_variants
from services.telegram_service import telegram_service
from utils.auth import require_admin, require_staff

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/subscriptions", tags=["Admin Subscriptions"])


class ModerationDecision(BaseModel):
    approve: bool
    comment: Optional[str] = None


class VerificationDecision(BaseModel):
    verified: bool


async def _photo_is_referenced(db: AsyncSession, url: str) -> bool:
    """Query versions refer to the same disk file and must not break other cards."""
    path = url.split("?", 1)[0]
    same_file = lambda column: func.split_part(column, "?", 1) == path
    images = func.jsonb_array_elements_text(Product.images).table_valued("value")
    image_in_gallery = select(1).select_from(images).where(same_file(images.c.value)).correlate(Product).exists()
    references = (
        select(Channel.id).where(or_(same_file(Channel.avatar_url), same_file(Channel.cover_url))),
        select(Product.id).where(or_(same_file(Product.image_url), image_in_gallery)),
        select(ListingImage.id).where(same_file(ListingImage.url)),
        select(SellerProfile.id).where(same_file(SellerProfile.avatar_url)),
    )
    for statement in references:
        if (await db.execute(statement.limit(1))).first() is not None:
            return True
    return False


@router.get("/channel-photos")
async def list_channel_photos(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Минимальный список для удаления фото без доступа к данным подписок."""
    total = (await db.execute(select(func.count(Channel.id)))).scalar() or 0
    channels = (await db.execute(
        select(Channel).order_by(Channel.created_at.desc(), Channel.id)
        .offset(skip).limit(limit)
    )).scalars().all()
    return {"items": [{"id": str(c.id), "title": c.title,
                       "avatar_url": c.avatar_url, "cover_url": c.cover_url}
                      for c in channels], "total": total}


@router.delete("/channels/{channel_id}/photos/{kind}")
async def delete_channel_photo(
    channel_id: uuid.UUID,
    kind: Literal["avatar", "cover"],
    admin: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Канал не найден")
    url = getattr(channel, f"{kind}_url")
    if not url:
        raise HTTPException(status_code=400, detail="У канала нет этого фото")
    setattr(channel, f"{kind}_url", None)
    await subscription_service.sync_plan_products(db, channel)
    audit_service.log_action(
        db, admin, "photo.delete", target_type="channel", target_id=channel.id,
        details={"kind": f"channel_{kind}", "name": channel.title, "url": url},
    )
    owner = await db.get(User, channel.owner_user_id)
    await db.commit()
    try:
        if not await _photo_is_referenced(db, url):
            image_variants.remove(Path(settings.UPLOAD_DIR), url)
    except Exception as exc:
        logger.warning("[ADMIN] Файл канала не удалён: %s", exc)
    if owner and owner.telegram_id:
        label = "аватарку" if kind == "avatar" else "обложку"
        try:
            await telegram_service.send_message(
                owner.telegram_id,
                f"Модератор удалил {label} канала «{channel.title}». Добавьте другое фото.",
                parse_mode=None,
            )
        except Exception as exc:
            logger.warning("[ADMIN] Уведомление владельцу канала не отправлено: %s", exc)
    return {"deleted": True}


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
                "is_verified": c.is_verified,
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

    # Решение модератора и определяет, продаются подписки или нет: товары
    # тарифов заведены ещё до модерации и до этого момента погашены.
    await subscription_service.sync_plan_products(db, channel)
    await db.commit()

    return {"status": channel.status.value}


@router.post("/channels/{channel_id}/verify")
async def set_channel_verified(
    channel_id: uuid.UUID,
    decision: VerificationDecision,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Ставит или снимает галочку проверенного автора.

    Отдельно от модерации канала: одобрение означает «подписки можно
    продавать», галочка — «площадка подтвердила, кто за каналом стоит». Это
    разные решения, и второе принимается реже.
    """
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel.is_verified = decision.verified
    await db.commit()
    return {"is_verified": channel.is_verified}


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
    await subscription_service.sync_plan_products(db, channel)
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
