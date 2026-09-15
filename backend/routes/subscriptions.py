"""
Подписки: каталог, кабинет автора, мои подписки.

Модерация каналов — в routes/admin_subscriptions.py.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models.product import Product
from models.subscription import (
    Channel, ChannelStatus, Subscription, SubscriptionPlan, SubscriptionStatus,
)
from models.user import User
from services import settings_service, subscription_service, terms_service
from services.telegram_service import TelegramApiError, channel_access
from utils.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subscriptions", tags=["Subscriptions"])


# ---------------------------------------------------------------------------
# Схемы
# ---------------------------------------------------------------------------

class ChannelCreate(BaseModel):
    # Либо @username, либо числовой chat_id канала
    chat_identifier: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    payout_wallet: str = Field(..., min_length=10, max_length=80)
    accept_terms: bool


class PlanCreate(BaseModel):
    title_ru: str = Field(..., min_length=1, max_length=255)
    title_en: str = Field(..., min_length=1, max_length=255)
    duration_days: int = Field(..., ge=1, le=3650)
    price_usd: Decimal = Field(..., gt=0, max_digits=10, decimal_places=2)


def _channel_dto(channel: Channel, plans: list[SubscriptionPlan] | None = None) -> dict:
    return {
        "id": str(channel.id),
        "title": channel.title,
        "username": channel.username,
        "description": channel.description,
        "avatar_url": channel.avatar_url,
        "status": channel.status.value,
        "bot_is_admin": channel.bot_is_admin,
        "bot_check_error": channel.bot_check_error,
        "plans": [
            {
                "id": str(p.id),
                "product_id": str(p.product_id) if p.product_id else None,
                "title_ru": p.title_ru,
                "title_en": p.title_en,
                "duration_days": p.duration_days,
                "price_usd": str(p.price_usd),
                "is_active": p.is_active,
            }
            for p in sorted(plans or [], key=lambda x: (x.sort_order, x.duration_days))
        ],
    }


# ---------------------------------------------------------------------------
# Каталог (публичный)
# ---------------------------------------------------------------------------

@router.get("/channels")
async def list_channels(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Опубликованные каналы с активными тарифами."""
    channels = (
        await db.execute(
            select(Channel)
            .options(selectinload(Channel.plans))
            .where(Channel.status == ChannelStatus.ACTIVE)
            .order_by(Channel.created_at.desc())
            .offset(skip).limit(limit)
        )
    ).scalars().all()

    return [
        _channel_dto(c, [p for p in c.plans if p.is_active])
        for c in channels
    ]


# ---------------------------------------------------------------------------
# Мои подписки
# ---------------------------------------------------------------------------

@router.get("/my")
async def my_subscriptions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    subscriptions = (
        await db.execute(
            select(Subscription)
            .options(selectinload(Subscription.channel), selectinload(Subscription.plan))
            .where(Subscription.user_id == user.id)
            .order_by(Subscription.created_at.desc())
        )
    ).scalars().all()

    now = datetime.utcnow()
    return [
        {
            "id": str(s.id),
            "channel_title": s.channel.title if s.channel else None,
            "channel_id": str(s.channel_id),
            "plan_title": s.plan.title_ru if s.plan else None,
            "status": s.status.value,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "days_left": (
                max((s.expires_at - now).days, 0)
                if s.expires_at and s.status == SubscriptionStatus.ACTIVE else None
            ),
            "joined": s.joined_at is not None,
            # Ссылка отдаётся только пока действует: одноразовая и с TTL
            "invite_link": (
                s.invite_link
                if s.invite_link
                and s.invite_link_expires_at
                and s.invite_link_expires_at > now
                else None
            ),
        }
        for s in subscriptions
    ]


@router.post("/{subscription_id}/invite")
async def reissue_invite(
    subscription_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Выдаёт ссылку заново.

    Ссылка одноразовая и живёт сутки — пользователь вполне может не успеть
    перейти. Пока подписка активна, он вправе получить новую.
    """
    subscription = (
        await db.execute(
            select(Subscription)
            .options(selectinload(Subscription.channel))
            .where(Subscription.id == subscription_id)
        )
    ).scalars().first()

    if not subscription or subscription.user_id != user.id:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if subscription.status != SubscriptionStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Subscription is not active")

    link = await subscription_service.issue_invite(db, subscription)
    if not link:
        raise HTTPException(
            status_code=503,
            detail="Не удалось создать ссылку. Администратор уведомлён.",
        )

    await db.commit()
    return {"invite_link": link}


# ---------------------------------------------------------------------------
# Кабинет автора
# ---------------------------------------------------------------------------

@router.get("/author/channels")
async def my_channels(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channels = (
        await db.execute(
            select(Channel)
            .options(selectinload(Channel.plans))
            .where(Channel.owner_user_id == user.id)
            .order_by(Channel.created_at.desc())
        )
    ).scalars().all()
    return [_channel_dto(c, c.plans) for c in channels]


@router.post("/author/channels")
async def connect_channel(
    payload: ChannelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Подключает канал автора.

    Права бота проверяются сразу: без них канал бесполезен — доступ невозможно
    ни выдать, ни отозвать. Канал создаётся в любом случае (чтобы автор мог
    добавить бота и нажать «Проверить»), но опубликовать его без прав нельзя.
    """
    if not payload.accept_terms:
        raise HTTPException(status_code=400, detail="Необходимо принять условия площадки")

    identifier: str | int = payload.chat_identifier.strip()
    if identifier.lstrip("-").isdigit():
        identifier = int(identifier)
    elif not str(identifier).startswith("@"):
        identifier = f"@{identifier}"

    try:
        chat = await channel_access.get_chat(identifier)
    except TelegramApiError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось найти канал: {e.description}. "
                   f"Добавьте бота в канал администратором и повторите.",
        )

    chat_id = chat["id"]

    existing = (
        await db.execute(select(Channel).where(Channel.telegram_chat_id == chat_id))
    ).scalars().first()
    if existing is not None:
        if existing.owner_user_id == user.id:
            raise HTTPException(status_code=400, detail="Этот канал уже подключён вами")
        raise HTTPException(status_code=400, detail="Этот канал уже подключён другим автором")

    terms_version = await terms_service.record(db, user, context="channel")

    channel = Channel(
        id=uuid.uuid4(),
        owner_user_id=user.id,
        telegram_chat_id=chat_id,
        title=chat.get("title") or str(chat_id),
        username=chat.get("username"),
        description=payload.description,
        payout_wallet=payload.payout_wallet.strip(),
        status=ChannelStatus.DRAFT,
        terms_version=terms_version,
        terms_accepted_at=datetime.utcnow(),
    )
    db.add(channel)
    await db.flush()

    await subscription_service.verify_channel(db, channel)
    await db.commit()

    return _channel_dto(channel, [])


@router.post("/author/channels/{channel_id}/verify")
async def verify_channel_rights(
    channel_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Перепроверка прав бота — автор жмёт после добавления бота в канал."""
    channel = await _own_channel(db, channel_id, user)
    ok, error = await subscription_service.verify_channel(db, channel)
    await db.commit()
    return {"bot_is_admin": ok, "error": error}


@router.post("/author/channels/{channel_id}/submit")
async def submit_for_moderation(
    channel_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = await _own_channel(db, channel_id, user)

    ok, error = await subscription_service.verify_channel(db, channel)
    if not ok:
        await db.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Бот должен быть администратором канала с правами приглашать "
                   f"и ограничивать участников. {error or ''}".strip(),
        )

    plans = (
        await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.channel_id == channel.id)
        )
    ).scalars().all()
    if not plans:
        raise HTTPException(status_code=400, detail="Добавьте хотя бы один тариф")

    channel.status = ChannelStatus.PENDING
    await db.commit()
    return {"status": channel.status.value}


@router.post("/author/channels/{channel_id}/plans")
async def create_plan(
    channel_id: uuid.UUID,
    payload: PlanCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Создаёт тариф и товар-витрину под него.

    Товар нужен, чтобы подписка продавалась через ту же корзину, заказ и
    оплату, что и остальные товары — отдельный путь покупки ради подписок
    заводить незачем, существующий уже протестирован.
    """
    channel = await _own_channel(db, channel_id, user)

    plan = SubscriptionPlan(
        id=uuid.uuid4(),
        channel_id=channel.id,
        title_ru=payload.title_ru,
        title_en=payload.title_en,
        duration_days=payload.duration_days,
        price_usd=payload.price_usd,
    )
    db.add(plan)
    await db.flush()

    category_id = await _subscriptions_category_id(db)
    product = Product(
        id=uuid.uuid4(),
        name_ru=f"{channel.title} — {payload.title_ru}",
        name_en=f"{channel.title} — {payload.title_en}",
        description_ru=channel.description or f"Доступ в закрытый канал на {payload.duration_days} дн.",
        description_en=channel.description or f"Private channel access for {payload.duration_days} days",
        price_usdt=payload.price_usd,
        image_url=channel.avatar_url or "/uploads/products/placeholder.png",
        category_id=category_id,
        type="subscription",
        min_quantity=1,
        stock=None,  # подписка не кончается
        # Ключ, по которому complete_order находит тариф при выдаче доступа
        content_data={"subscription_plan_id": str(plan.id)},
    )
    db.add(product)
    await db.flush()

    plan.product_id = product.id
    await db.commit()

    return {"id": str(plan.id), "product_id": str(product.id)}


async def _own_channel(db: AsyncSession, channel_id: uuid.UUID, user: User) -> Channel:
    channel = await db.get(Channel, channel_id)
    if not channel or (channel.owner_user_id != user.id and not user.is_admin):
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


async def _subscriptions_category_id(db: AsyncSession) -> uuid.UUID:
    """Категория «Подписки» создаётся при первом тарифе."""
    from models.category import Category

    category = (
        await db.execute(select(Category).where(Category.name_en == "Subscriptions"))
    ).scalars().first()
    if category is not None:
        return category.id

    category = Category(
        id=uuid.uuid4(), name_ru="Подписки", name_en="Subscriptions", sort_order=100
    )
    db.add(category)
    await db.flush()
    return category.id
