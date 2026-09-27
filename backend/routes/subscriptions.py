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

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models.order import OrderItem
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

# Картинка на случай канала без аватара. Файл создаётся при старте бэкенда
# (см. utils/placeholder.py): раньше сюда ссылались все товары подписок, а
# самого файла на диске не было — карточка выходила пустой.
PLACEHOLDER_IMAGE = "/uploads/products/placeholder.png"


# ---------------------------------------------------------------------------
# Схемы
# ---------------------------------------------------------------------------

class ChannelCreate(BaseModel):
    # Либо @username, либо числовой chat_id канала
    chat_identifier: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    description_en: Optional[str] = Field(None, max_length=2000)
    payout_wallet: str = Field(..., min_length=10, max_length=80)
    accept_terms: bool


class ChannelUpdate(BaseModel):
    description: Optional[str] = Field(None, max_length=2000)
    description_en: Optional[str] = Field(None, max_length=2000)
    payout_wallet: Optional[str] = Field(None, min_length=10, max_length=80)


class PlanCreate(BaseModel):
    title_ru: str = Field(..., min_length=1, max_length=255)
    title_en: str = Field(..., min_length=1, max_length=255)
    duration_days: int = Field(..., ge=1, le=3650)
    price_usd: Decimal = Field(..., gt=0, max_digits=10, decimal_places=2)


class PlanUpdate(BaseModel):
    title_ru: Optional[str] = Field(None, min_length=1, max_length=255)
    title_en: Optional[str] = Field(None, min_length=1, max_length=255)
    duration_days: Optional[int] = Field(None, ge=1, le=3650)
    price_usd: Optional[Decimal] = Field(None, gt=0, max_digits=10, decimal_places=2)
    is_active: Optional[bool] = None


def _channel_dto(channel: Channel, plans: list[SubscriptionPlan] | None = None) -> dict:
    return {
        "id": str(channel.id),
        "title": channel.title,
        "username": channel.username,
        "description": channel.description,
        "description_en": channel.description_en,
        "avatar_url": channel.avatar_url,
        "cover_url": channel.cover_url,
        "status": channel.status.value,
        "is_verified": channel.is_verified,
        "moderation_comment": channel.moderation_comment,
        "payout_wallet": channel.payout_wallet,
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
        description_en=payload.description_en,
        payout_wallet=payload.payout_wallet.strip(),
        status=ChannelStatus.DRAFT,
        terms_version=terms_version,
        terms_accepted_at=datetime.utcnow(),
    )
    db.add(channel)
    await _ensure_store(db, user, channel)
    await db.flush()

    # Аватар забираем из того же ответа getChat, что уже в руках: своего поля
    # под картинку у канала нет — автор её уже загрузил в Telegram.
    await subscription_service.refresh_avatar(channel, chat)
    await subscription_service.verify_channel(db, channel)
    await db.commit()

    return _channel_dto(channel, [])


async def _ensure_store(db: AsyncSession, user: User, channel: Channel) -> None:
    """
    У автора канала должен быть магазин.

    Подписка продаётся от имени магазина автора, а не от имени канала. Если
    магазина ещё нет, заводим его прямо здесь: всё нужное автор только что
    указал — кошелёк для выплат и согласие с условиями. Название берём по
    каналу, переименовать его можно в настройках магазина.

    Без этого подписка оставалась бы в отдельном магазине-канале у всех, кто
    ничего, кроме неё, не продаёт, — то есть почти у всех.
    """
    from models.p2p import SellerProfile

    existing = (
        await db.execute(select(SellerProfile).where(SellerProfile.user_id == user.id))
    ).scalars().first()
    if existing is not None:
        return

    db.add(SellerProfile(
        id=uuid.uuid4(),
        user_id=user.id,
        display_name=await _free_store_name(db, channel.title[:100]),
        # Имя подставлено по каналу, а не выбрано владельцем: один раз
        # назвать свой магазин он ещё сможет
        name_locked=False,
        payout_wallet=channel.payout_wallet or "",
        terms_version=channel.terms_version,
        terms_accepted_at=channel.terms_accepted_at,
    ))


async def _free_store_name(db: AsyncSession, base: str) -> str:
    """
    Свободное название магазина рядом с желаемым.

    Названия магазинов уникальны, а канал с таким именем мог существовать
    раньше магазина. Ронять подключение канала из-за этого нельзя: имя
    здесь временное, владелец всё равно назовёт магазин сам.
    """
    from models.p2p import SellerProfile

    name = base.strip() or "Магазин"
    for attempt in range(1, 50):
        taken = (
            await db.execute(
                select(SellerProfile.id).where(
                    func.lower(SellerProfile.display_name) == name.lower()
                ).limit(1)
            )
        ).scalars().first()
        if taken is None:
            return name
        name = f"{base[:88].strip()} #{attempt + 1}"
    return f"{base[:80].strip()} {uuid.uuid4().hex[:6]}"


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


@router.post("/author/channels/{channel_id}/cover")
async def upload_channel_cover(
    channel_id: uuid.UUID,
    image: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Обложка подписок канала.

    Картинку товара тариф брал из аватара, а аватар подтягивается из
    Telegram: у канала без фотографии его нет вовсе, и подписка стояла в
    каталоге с серой заглушкой рядом с обычными товарами.

    Проверку файла берём у объявлений: там тип определяется по содержимому
    через Pillow, а не по расширению и не по content-type — и то и другое
    подделывается тривиально.
    """
    # Импорт внутри функции: модули роутов грузятся по очереди, и
    # верхнеуровневый ссылался бы на порядок регистрации в main.py
    from routes.p2p import _save_listing_image

    channel = await _own_channel(db, channel_id, user)

    channel.cover_url = await _save_listing_image(image, subdir="channels")
    # Картинка видна в каталоге, поэтому сразу переносим её в товары тарифов
    await subscription_service.sync_plan_products(db, channel)
    await db.commit()

    return {"cover_url": channel.cover_url}


@router.delete("/author/channels/{channel_id}/cover")
async def delete_channel_cover(
    channel_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Снять обложку. Товары тарифов возвращаются к аватару канала, а если
    его нет — к заглушке.

    Файл с диска не удаляем: он мог уже уйти в товар как картинка, и
    удаление оставило бы битую ссылку до ближайшей пересборки.
    """
    channel = await _own_channel(db, channel_id, user)
    channel.cover_url = None

    picture = channel.avatar_url or PLACEHOLDER_IMAGE
    plans = (
        await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.channel_id == channel.id)
        )
    ).scalars().all()
    for plan in plans:
        if plan.product_id:
            product = await db.get(Product, plan.product_id)
            if product is not None:
                product.image_url = picture

    await db.commit()
    return {"cover_url": None}


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
        # Английское описание берём английское: раньше сюда шло русское, и
        # подписка в англоязычном каталоге читалась по-русски
        description_en=(channel.description_en or channel.description
                        or f"Private channel access for {payload.duration_days} days"),
        price_usdt=payload.price_usd,
        image_url=channel.cover_url or channel.avatar_url or PLACEHOLDER_IMAGE,
        category_id=category_id,
        type="subscription",
        min_quantity=1,
        stock=None,  # подписка не кончается
        # Владелец — автор канала. По этому полю витрина находит его магазин:
        # подписка продаётся оттуда же, откуда остальные его товары, а не
        # отдельным магазином-каналом.
        owner_user_id=channel.owner_user_id,
        # Товар заводится вместе с тарифом, то есть ДО модерации канала.
        # Без этой привязки подписка попадала в каталог, пока канал ещё лежал
        # в черновике, — продавать её можно только у опубликованного канала.
        is_active=channel.status == ChannelStatus.ACTIVE,
        # Ключ, по которому complete_order находит тариф при выдаче доступа
        content_data={"subscription_plan_id": str(plan.id)},
    )
    db.add(product)
    await db.flush()

    plan.product_id = product.id
    await db.commit()

    return {"id": str(plan.id), "product_id": str(product.id)}


@router.patch("/author/channels/{channel_id}")
async def update_channel(
    channel_id: uuid.UUID,
    payload: ChannelUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Правка канала.

    Кошелёк меняется когда угодно: он не публичный и покупателя не касается.
    Описание — публичный текст, он и есть предмет модерации, поэтому правка
    описания у опубликованного канала возвращает его в черновик. Иначе можно
    подать безобидный текст, дождаться одобрения и подменить его на что
    угодно — ровно от этого защищён и путь объявлений (см. _assert_editable
    в routes/p2p.py).
    """
    channel = await _own_channel(db, channel_id, user)

    if payload.payout_wallet is not None:
        channel.payout_wallet = payload.payout_wallet.strip()

    changed_text = False

    if payload.description is not None:
        new_description = payload.description.strip() or None
        if new_description != channel.description:
            channel.description = new_description
            changed_text = True

    # Английское описание проверяет тот же модератор, поэтому и оно уводит
    # канал на повторную проверку
    if payload.description_en is not None:
        new_english = payload.description_en.strip() or None
        if new_english != channel.description_en:
            channel.description_en = new_english
            changed_text = True

    if changed_text and channel.status == ChannelStatus.ACTIVE:
        channel.status = ChannelStatus.DRAFT
        channel.moderation_comment = (
            "Описание изменено — канал снят с публикации до повторной проверки"
        )

    await subscription_service.sync_plan_products(db, channel)
    await db.commit()

    plans = (
        await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.channel_id == channel.id)
        )
    ).scalars().all()
    return _channel_dto(channel, plans)


@router.post("/author/channels/{channel_id}/unpublish")
async def unpublish_channel(
    channel_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Снимает канал с продажи по воле автора.

    Уже купленные подписки не трогаем: человек заплатил за срок и должен его
    отходить. Снимается только возможность купить новую.
    """
    channel = await _own_channel(db, channel_id, user)
    if channel.status != ChannelStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Канал и так не опубликован")

    channel.status = ChannelStatus.DRAFT
    await subscription_service.sync_plan_products(db, channel)
    await db.commit()
    return {"status": channel.status.value}


@router.delete("/author/channels/{channel_id}")
async def delete_channel(
    channel_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Удаляет канал, который ничего не продал.

    Если подписки были — удалять нельзя ни в каком виде: Subscription висит на
    канале с ondelete=CASCADE, и удаление стёрло бы историю оплат вместе с
    журналом выдачи доступа. Для этого случая есть «снять с продажи».
    """
    channel = await _own_channel(db, channel_id, user)

    sold = (
        await db.execute(
            select(func.count()).select_from(Subscription)
            .where(Subscription.channel_id == channel.id)
        )
    ).scalar() or 0
    if sold:
        raise HTTPException(
            status_code=400,
            detail=f"По каналу есть подписки ({sold}) — удалить нельзя, "
                   f"историю оплат нужно сохранить. Снимите канал с продажи.",
        )

    # Товары тарифов гасим, а не удаляем: по ним могли быть неоплаченные
    # заказы, и удаление оставило бы битые строки в истории.
    channel.status = ChannelStatus.SUSPENDED
    await subscription_service.sync_plan_products(db, channel)
    await db.flush()

    await db.delete(channel)
    await db.commit()
    return {"deleted": True}


@router.patch("/author/channels/{channel_id}/plans/{plan_id}")
async def update_plan(
    channel_id: uuid.UUID,
    plan_id: uuid.UUID,
    payload: PlanUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Правка тарифа: название, срок, цена, продаётся или нет.

    Повторной модерации не требует, в отличие от описания канала: здесь нечего
    подменить — цена это число, срок это число, а название видно в каталоге
    рядом с именем канала, которое берётся из Telegram.

    Срок меняется только для будущих покупок. Уже выданным подпискам дата
    окончания не пересчитывается: человек купил конкретный срок.
    """
    channel = await _own_channel(db, channel_id, user)
    plan = await db.get(SubscriptionPlan, plan_id)
    if plan is None or plan.channel_id != channel.id:
        raise HTTPException(status_code=404, detail="Тариф не найден")

    if payload.title_ru is not None:
        plan.title_ru = payload.title_ru.strip()
    if payload.title_en is not None:
        plan.title_en = payload.title_en.strip()
    if payload.duration_days is not None:
        plan.duration_days = payload.duration_days
    if payload.price_usd is not None:
        plan.price_usd = payload.price_usd
    if payload.is_active is not None:
        plan.is_active = payload.is_active

    if plan.product_id:
        product = await db.get(Product, plan.product_id)
        if product is not None:
            product.price_usdt = plan.price_usd

    # Название и активность товара приводит в порядок общий синхронизатор —
    # он же знает про статус канала
    await subscription_service.sync_plan_products(db, channel)
    await db.commit()

    return {"id": str(plan.id), "is_active": plan.is_active}


@router.delete("/author/channels/{channel_id}/plans/{plan_id}")
async def delete_plan(
    channel_id: uuid.UUID,
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Удаляет тариф, по которому никто не покупал.

    Проданный тариф удалить нельзя — на него ссылаются подписки и заказы.
    Такой отключается: из каталога пропадает, история остаётся.
    """
    channel = await _own_channel(db, channel_id, user)
    plan = await db.get(SubscriptionPlan, plan_id)
    if plan is None or plan.channel_id != channel.id:
        raise HTTPException(status_code=404, detail="Тариф не найден")

    sold = (
        await db.execute(
            select(func.count()).select_from(Subscription)
            .where(Subscription.plan_id == plan.id)
        )
    ).scalar() or 0
    if sold:
        raise HTTPException(
            status_code=400,
            detail=f"По тарифу есть подписки ({sold}) — удалить нельзя. "
                   f"Отключите его, чтобы он пропал из каталога.",
        )

    product_id = plan.product_id
    await db.delete(plan)
    await db.flush()

    if product_id:
        ordered = (
            await db.execute(
                select(func.count()).select_from(OrderItem)
                .where(OrderItem.product_id == product_id)
            )
        ).scalar() or 0
        product = await db.get(Product, product_id)
        if product is not None:
            # В заказах товар мог остаться даже без подписки: заказ создали,
            # но не оплатили. Такой товар гасим, а не удаляем.
            if ordered:
                product.is_active = False
            else:
                await db.delete(product)

    await db.commit()
    return {"deleted": True}


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
