"""
P2P: кабинет продавца, заявки на размещение, действия по сделкам.

Модерация — в routes/admin_p2p.py.
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, UploadFile,
)
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import get_db
from models.p2p import (
    Deal, DealStatus, ListingImage, ListingStatus, ProductListing,
    SellerProfile, SellerStatus,
)
from models.user import User
from services import deal_service, relay_service, settings_service, terms_service
from services.money import from_minor
from utils.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/p2p", tags=["P2P"])

# Разрешаем только растровые форматы, которые точно безопасно отдавать
# браузеру. SVG исключён намеренно: он может содержать скрипты.
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_IMAGES_PER_LISTING = 8


# ---------------------------------------------------------------------------
# Схемы
# ---------------------------------------------------------------------------

class SellerRegister(BaseModel):
    display_name: str = Field(..., min_length=2, max_length=100)
    payout_wallet: str = Field(..., min_length=10, max_length=80)
    accept_terms: bool


class ListingCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=500)
    description: str = Field(..., min_length=10, max_length=5000)
    price_usd: Decimal = Field(..., gt=0, max_digits=10, decimal_places=2)
    category_id: Optional[uuid.UUID] = None
    accept_terms: bool


class DisputeOpen(BaseModel):
    reason: str = Field(..., min_length=10, max_length=2000)


# ---------------------------------------------------------------------------
# Вспомогательное
# ---------------------------------------------------------------------------

async def _get_seller(db: AsyncSession, user: User) -> SellerProfile:
    profile = (
        await db.execute(select(SellerProfile).where(SellerProfile.user_id == user.id))
    ).scalars().first()
    if profile is None:
        raise HTTPException(status_code=404, detail="Сначала зарегистрируйтесь как продавец")
    return profile


def _assert_can_sell(profile: SellerProfile) -> None:
    if profile.status == SellerStatus.BANNED:
        raise HTTPException(status_code=403, detail="Аккаунт продавца заблокирован")
    if profile.status == SellerStatus.RESTRICTED:
        if profile.restricted_until and profile.restricted_until > datetime.utcnow():
            raise HTTPException(
                status_code=403,
                detail=f"Размещение ограничено до {profile.restricted_until:%d.%m.%Y %H:%M}. "
                       f"{profile.restriction_reason or ''}".strip(),
            )


async def _save_listing_image(upload: UploadFile) -> str:
    """
    Сохраняет фото объявления с проверками.

    Штатный save_image в routes/products.py не проверяет ни тип, ни размер —
    для товаров площадки это терпимо (их заводит админ), для файлов от
    пользователей нет. Тип определяется по СОДЕРЖИМОМУ через Pillow, а не по
    расширению и не по content-type: и то и другое подделывается тривиально.
    """
    content = await upload.read()

    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Файл больше {settings.MAX_UPLOAD_SIZE // 1024 // 1024} МБ",
        )

    try:
        image = Image.open(io.BytesIO(content))
        image.verify()          # ловит битые и поддельные файлы
        fmt = (image.format or "").upper()
    except Exception:
        raise HTTPException(status_code=400, detail="Файл не является изображением")

    if fmt not in ALLOWED_IMAGE_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Формат {fmt or 'неизвестный'} не поддерживается. "
                   f"Допустимы: {', '.join(sorted(ALLOWED_IMAGE_FORMATS))}",
        )

    extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[fmt]
    file_name = f"{uuid.uuid4()}{extension}"
    directory = Path(settings.UPLOAD_DIR) / "listings"
    directory.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(directory / file_name, "wb") as out:
        await out.write(content)

    return f"/uploads/listings/{file_name}"


# ---------------------------------------------------------------------------
# Продавец
# ---------------------------------------------------------------------------

@router.get("/seller/me")
async def seller_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = (
        await db.execute(select(SellerProfile).where(SellerProfile.user_id == user.id))
    ).scalars().first()
    if profile is None:
        return {"registered": False}

    return {
        "registered": True,
        "display_name": profile.display_name,
        "payout_wallet": profile.payout_wallet,
        "status": profile.status.value,
        "restricted_until": (
            profile.restricted_until.isoformat() if profile.restricted_until else None
        ),
        "restriction_reason": profile.restriction_reason,
        "rating": profile.rating,
        "rating_count": profile.rating_count,
        "deals_completed": profile.deals_completed,
    }


@router.post("/seller/register")
async def register_seller(
    payload: SellerRegister,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not payload.accept_terms:
        raise HTTPException(status_code=400, detail="Необходимо принять условия площадки")

    existing = (
        await db.execute(select(SellerProfile).where(SellerProfile.user_id == user.id))
    ).scalars().first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Вы уже зарегистрированы как продавец")

    version = await terms_service.record(db, user, context="listing")
    profile = SellerProfile(
        id=uuid.uuid4(),
        user_id=user.id,
        display_name=payload.display_name.strip(),
        payout_wallet=payload.payout_wallet.strip(),
        terms_version=version,
        terms_accepted_at=datetime.utcnow(),
    )
    db.add(profile)
    await db.commit()

    return {"registered": True, "status": profile.status.value}


@router.get("/seller/listings")
async def my_listings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_seller(db, user)
    listings = (
        await db.execute(
            select(ProductListing)
            .options(selectinload(ProductListing.images))
            .where(ProductListing.seller_id == profile.id)
            .order_by(ProductListing.created_at.desc())
        )
    ).scalars().all()

    return [
        {
            "id": str(l.id),
            "name": l.name,
            "description": l.description,
            "price_usd": str(l.price_usd),
            "status": l.status.value,
            "moderation_comment": l.moderation_comment,
            "product_id": str(l.product_id) if l.product_id else None,
            "images": [img.url for img in l.images],
            "created_at": l.created_at.isoformat(),
        }
        for l in listings
    ]


@router.post("/seller/listings")
async def create_listing(
    payload: ListingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Создаёт заявку на размещение товара.

    Антифрод: ограничивается количество заявок, одновременно висящих на
    модерации. Без лимита один человек может завалить очередь сотней заявок
    и модерация встанет.
    """
    if not payload.accept_terms:
        raise HTTPException(status_code=400, detail="Необходимо принять условия площадки")

    profile = await _get_seller(db, user)
    _assert_can_sell(profile)

    max_pending = await settings_service.get_int(db, "p2p_max_pending_listings")
    pending = (
        await db.execute(
            select(ProductListing).where(
                ProductListing.seller_id == profile.id,
                ProductListing.status == ListingStatus.PENDING,
            )
        )
    ).scalars().all()

    if len(pending) >= max_pending:
        raise HTTPException(
            status_code=429,
            detail=f"У вас уже {len(pending)} заявок на модерации (лимит {max_pending}). "
                   f"Дождитесь решения по ним.",
        )

    listing = ProductListing(
        id=uuid.uuid4(),
        seller_id=profile.id,
        category_id=payload.category_id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        price_usd=payload.price_usd,
        status=ListingStatus.DRAFT,
    )
    db.add(listing)
    await terms_service.record(db, user, context="listing", ref_type="listing", ref_id=listing.id)
    await db.commit()

    return {"id": str(listing.id), "status": listing.status.value}


@router.post("/seller/listings/{listing_id}/images")
async def upload_listing_image(
    listing_id: uuid.UUID,
    image: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_seller(db, user)
    listing = await _own_listing(db, listing_id, profile)

    if listing.status not in (ListingStatus.DRAFT, ListingStatus.REJECTED):
        raise HTTPException(status_code=400, detail="Фото можно добавлять только до отправки на модерацию")

    count = len(listing.images)
    if count >= MAX_IMAGES_PER_LISTING:
        raise HTTPException(status_code=400, detail=f"Максимум {MAX_IMAGES_PER_LISTING} фото")

    url = await _save_listing_image(image)
    db.add(ListingImage(id=uuid.uuid4(), listing_id=listing.id, url=url, sort_order=count))
    await db.commit()

    return {"url": url}


@router.post("/seller/listings/{listing_id}/submit")
async def submit_listing(
    listing_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_seller(db, user)
    _assert_can_sell(profile)
    listing = await _own_listing(db, listing_id, profile)

    if listing.status not in (ListingStatus.DRAFT, ListingStatus.REJECTED):
        raise HTTPException(status_code=400, detail=f"Заявка уже в статусе {listing.status.value}")
    if not listing.images:
        raise HTTPException(status_code=400, detail="Добавьте хотя бы одно фото")

    listing.status = ListingStatus.PENDING
    listing.moderation_comment = None
    await db.commit()

    from services.telegram_service import telegram_service
    for chat_id in telegram_service.admin_chat_ids:
        try:
            await telegram_service.send_message(
                chat_id,
                f"Новая заявка на размещение\n"
                f"Продавец: {profile.display_name}\n"
                f"Товар: {listing.name}\n"
                f"Цена: ${listing.price_usd}\n\n"
                f"Проверьте в админке",
                parse_mode=None,
            )
        except Exception as e:
            logger.warning("[P2P] Не удалось уведомить о заявке: %s", e)

    return {"status": listing.status.value}


async def _own_listing(
    db: AsyncSession, listing_id: uuid.UUID, profile: SellerProfile
) -> ProductListing:
    listing = (
        await db.execute(
            select(ProductListing)
            .options(selectinload(ProductListing.images))
            .where(ProductListing.id == listing_id)
        )
    ).scalars().first()
    if listing is None or listing.seller_id != profile.id:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return listing


# ---------------------------------------------------------------------------
# Сделки
# ---------------------------------------------------------------------------

def _deal_dto(deal: Deal, viewer: User) -> dict:
    return {
        "id": str(deal.id),
        "number": deal.number,
        "product_name": deal.product_name,
        "role": "buyer" if deal.buyer_id == viewer.id else "seller",
        "status": deal.status.value,
        "amount_ton": str(from_minor(deal.amount_nano, "TON")),
        "seller_amount_ton": str(from_minor(deal.seller_amount_nano, "TON")),
        "confirm_deadline_at": (
            deal.confirm_deadline_at.isoformat() if deal.confirm_deadline_at else None
        ),
        "chat_closed": deal.chat_closed,
        "dispute_reason": deal.dispute_reason,
        "created_at": deal.created_at.isoformat(),
    }


@router.get("/deals")
async def my_deals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deals = (
        await db.execute(
            select(Deal)
            .where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id))
            .order_by(Deal.created_at.desc())
        )
    ).scalars().all()
    return [_deal_dto(d, user) for d in deals]


async def _participant_deal(db: AsyncSession, deal_id: uuid.UUID, user: User) -> Deal:
    deal = await db.get(Deal, deal_id)
    if deal is None or user.id not in (deal.buyer_id, deal.seller_id):
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    return deal


@router.post("/deals/{deal_id}/delivered")
async def mark_delivered(
    deal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Продавец отмечает отправку. С этого момента идёт отсчёт автоподтверждения."""
    deal = await _participant_deal(db, deal_id, user)
    try:
        await deal_service.mark_delivered(db, deal, user)
    except deal_service.DealError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await relay_service.post_system_message(
        db, deal,
        f"Продавец отметил отправку. Подтвердите получение — после этого деньги "
        f"уйдут продавцу. Если не подтвердить, сделка закроется автоматически "
        f"{deal.confirm_deadline_at:%d.%m.%Y}.",
    )
    await db.commit()
    return _deal_dto(deal, user)


@router.post("/deals/{deal_id}/confirm")
async def confirm_receipt(
    deal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Покупатель подтверждает получение — деньги уходят продавцу.

    Это необратимо: после подтверждения открыть спор нельзя, о чём сказано в
    условиях площадки.
    """
    deal = await _participant_deal(db, deal_id, user)
    try:
        await deal_service.confirm_receipt(db, deal, user)
    except deal_service.DealError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await relay_service.post_system_message(
        db, deal, "Покупатель подтвердил получение. Сделка завершена, чат закрыт.",
    )
    await relay_service.close_chat(db, deal)
    await db.commit()
    return _deal_dto(deal, user)


@router.post("/deals/{deal_id}/dispute")
async def open_dispute(
    deal_id: uuid.UUID,
    payload: DisputeOpen,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deal = await _participant_deal(db, deal_id, user)
    try:
        await deal_service.open_dispute(db, deal, user, payload.reason)
    except deal_service.DealError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await relay_service.post_system_message(
        db, deal,
        "Открыт спор. Деньги остаются у платформы до решения администрации. "
        "Продолжайте переписку здесь — она будет учтена при разборе.",
    )
    await db.commit()

    from services.telegram_service import telegram_service
    for chat_id in telegram_service.admin_chat_ids:
        try:
            await telegram_service.send_message(
                chat_id,
                f"Открыт спор по сделке #{deal.number}\n"
                f"Товар: {deal.product_name}\n"
                f"Сумма: {from_minor(deal.amount_nano, 'TON')} TON\n"
                f"Причина: {payload.reason[:300]}\n\n"
                f"Разберите в админке",
                parse_mode=None,
            )
        except Exception as e:
            logger.warning("[P2P] Не удалось уведомить о споре: %s", e)

    return _deal_dto(deal, user)


@router.post("/deals/{deal_id}/activate")
async def set_active_deal(
    deal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Делает сделку активной для релей-чата.

    Нужно, когда у человека несколько открытых сделок: бот не угадывает, кому
    адресовано сообщение, а использует эту.
    """
    deal = await _participant_deal(db, deal_id, user)
    await relay_service.set_active_deal(db, user, deal)
    await db.commit()
    return {"active_deal": deal.number}


@router.get("/deals/{deal_id}/messages")
async def deal_messages(
    deal_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """История переписки — чтобы стороны видели её и в приложении."""
    from models.p2p import DealMessage

    deal = await _participant_deal(db, deal_id, user)
    rows = (
        await db.execute(
            select(DealMessage)
            .where(DealMessage.deal_id == deal.id)
            .order_by(DealMessage.created_at)
            .offset(skip).limit(limit)
        )
    ).scalars().all()

    return [
        {
            "direction": m.direction.value,
            "mine": m.sender_id == user.id,
            "text": m.text,
            "media_type": m.media_type,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]
