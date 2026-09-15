"""Админка P2P: модерация заявок, сделки, разбор споров."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models.category import Category
from models.p2p import (
    Deal, DealMessage, DealStatus, ListingStatus, ProductListing,
    SellerProfile, SellerStatus,
)
from models.product import Product
from models.user import User
from services import deal_service, relay_service, settings_service
from services.money import from_minor
from utils.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/p2p", tags=["Admin P2P"])


class ModerationDecision(BaseModel):
    approve: bool
    comment: Optional[str] = Field(None, max_length=1000)


class DisputeResolution(BaseModel):
    # True — деньги продавцу, False — возврат покупателю
    release: bool
    comment: Optional[str] = Field(None, max_length=2000)


class SellerAction(BaseModel):
    status: SellerStatus
    reason: Optional[str] = Field(None, max_length=1000)
    restrict_days: Optional[int] = Field(None, ge=1, le=365)


# ---------------------------------------------------------------------------
# Модерация заявок
# ---------------------------------------------------------------------------

@router.get("/listings")
async def list_listings(
    status: Optional[ListingStatus] = Query(ListingStatus.PENDING),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ProductListing).options(
        selectinload(ProductListing.images),
        selectinload(ProductListing.seller).selectinload(SellerProfile.user),
    )
    if status:
        stmt = stmt.where(ProductListing.status == status)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await db.execute(
            stmt.order_by(ProductListing.created_at).offset(skip).limit(limit)
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(l.id),
                "name": l.name,
                "description": l.description,
                "price_usd": str(l.price_usd),
                "status": l.status.value,
                "images": [img.url for img in l.images],
                "seller": {
                    "id": str(l.seller.id),
                    "display_name": l.seller.display_name,
                    "username": l.seller.user.username if l.seller.user else None,
                    "telegram_id": l.seller.user.telegram_id if l.seller.user else None,
                    "status": l.seller.status.value,
                    "rating": l.seller.rating,
                    "deals_completed": l.seller.deals_completed,
                    "rejected_streak": l.seller.rejected_streak,
                },
                "created_at": l.created_at.isoformat(),
            }
            for l in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.post("/listings/{listing_id}/moderate")
async def moderate_listing(
    listing_id: uuid.UUID,
    decision: ModerationDecision,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Одобрение или отказ по заявке.

    При одобрении создаётся товар в каталоге с пометкой P2P. При отказе
    растёт счётчик отказов ПОДРЯД, и по достижении порога продавец временно
    ограничивается. Счётчик обнуляется при первом одобрении: продавец с сотней
    товаров и парой старых отказов не должен быть ограничен навсегда.
    """
    listing = (
        await db.execute(
            select(ProductListing)
            .options(selectinload(ProductListing.images), selectinload(ProductListing.seller))
            .where(ProductListing.id == listing_id)
        )
    ).scalars().first()
    if listing is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if listing.status != ListingStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Заявка в статусе {listing.status.value}")

    seller = listing.seller
    listing.moderator_id = admin.id
    listing.moderation_comment = decision.comment
    listing.moderated_at = datetime.utcnow()

    if not decision.approve:
        listing.status = ListingStatus.REJECTED
        seller.rejected_streak += 1

        threshold = await settings_service.get_int(db, "p2p_reject_block_threshold")
        restricted = False
        if seller.rejected_streak >= threshold:
            seller.status = SellerStatus.RESTRICTED
            seller.restricted_until = datetime.utcnow() + timedelta(days=7)
            seller.restriction_reason = (
                f"{seller.rejected_streak} отказа подряд при модерации"
            )
            restricted = True

        await db.commit()
        await _notify_seller(
            db, seller,
            f"Заявка «{listing.name}» отклонена.\n"
            + (f"Причина: {decision.comment}\n" if decision.comment else "")
            + ("\nРазмещение временно ограничено на 7 дней." if restricted else ""),
        )
        return {"status": listing.status.value, "seller_restricted": restricted}

    # --- Одобрение: заводим товар в каталоге ---
    category_id = listing.category_id or await _default_category_id(db)
    image_url = listing.images[0].url if listing.images else "/uploads/products/placeholder.png"

    product = Product(
        id=uuid.uuid4(),
        name_ru=listing.name,
        name_en=listing.name,
        description_ru=listing.description,
        description_en=listing.description,
        price_usdt=listing.price_usd,
        image_url=image_url,
        category_id=category_id,
        type="p2p",
        min_quantity=1,
        max_quantity=1,          # товар пользователя продаётся поштучно
        stock=None,
        content_data={"listing_id": str(listing.id)},
        owner_user_id=seller.user_id,
        is_p2p=True,
    )
    db.add(product)
    await db.flush()

    listing.product_id = product.id
    listing.status = ListingStatus.APPROVED
    seller.rejected_streak = 0    # серия отказов прервана
    await db.commit()

    await _notify_seller(db, seller, f"Заявка «{listing.name}» одобрена, товар опубликован.")
    return {"status": listing.status.value, "product_id": str(product.id)}


async def _default_category_id(db: AsyncSession) -> uuid.UUID:
    category = (
        await db.execute(select(Category).where(Category.name_en == "User items"))
    ).scalars().first()
    if category is not None:
        return category.id
    category = Category(
        id=uuid.uuid4(), name_ru="Товары пользователей", name_en="User items", sort_order=200
    )
    db.add(category)
    await db.flush()
    return category.id


async def _notify_seller(db: AsyncSession, seller: SellerProfile, text: str) -> None:
    from services.telegram_service import telegram_service

    user = await db.get(User, seller.user_id)
    if not user:
        return
    try:
        await telegram_service.send_message(user.telegram_id, text, parse_mode=None)
    except Exception as e:
        logger.warning("[P2P] Не удалось уведомить продавца: %s", e)


# ---------------------------------------------------------------------------
# Продавцы
# ---------------------------------------------------------------------------

@router.get("/sellers")
async def list_sellers(
    status: Optional[SellerStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SellerProfile).options(selectinload(SellerProfile.user))
    if status:
        stmt = stmt.where(SellerProfile.status == status)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await db.execute(stmt.order_by(SellerProfile.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(s.id),
                "display_name": s.display_name,
                "username": s.user.username if s.user else None,
                "telegram_id": s.user.telegram_id if s.user else None,
                "status": s.status.value,
                "rating": s.rating,
                "rating_count": s.rating_count,
                "deals_completed": s.deals_completed,
                "rejected_streak": s.rejected_streak,
                "payout_wallet": s.payout_wallet,
                "restricted_until": s.restricted_until.isoformat() if s.restricted_until else None,
            }
            for s in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.post("/sellers/{seller_id}/status")
async def change_seller_status(
    seller_id: uuid.UUID,
    payload: SellerAction,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Блокировка, ограничение или снятие ограничений с продавца.

    Блокировка продавца НЕ трогает его открытые сделки: покупатели уже
    заплатили, и их деньги должны дойти до логического конца через обычный
    сценарий или спор.
    """
    seller = await db.get(SellerProfile, seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Продавец не найден")

    seller.status = payload.status
    seller.restriction_reason = payload.reason

    if payload.status == SellerStatus.RESTRICTED and payload.restrict_days:
        seller.restricted_until = datetime.utcnow() + timedelta(days=payload.restrict_days)
    elif payload.status == SellerStatus.ACTIVE:
        seller.restricted_until = None
        seller.restriction_reason = None
        seller.rejected_streak = 0

    # Блокировка продавца снимает его товары с витрины: продавать он больше
    # не может, а висящие объявления вводили бы покупателей в заблуждение
    if payload.status == SellerStatus.BANNED:
        products = (
            await db.execute(select(Product).where(Product.owner_user_id == seller.user_id))
        ).scalars().all()
        for product in products:
            product.stock = 0

    await db.commit()
    return {"status": seller.status.value}


# ---------------------------------------------------------------------------
# Сделки и споры
# ---------------------------------------------------------------------------

@router.get("/deals")
async def list_deals(
    status: Optional[DealStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Deal).options(selectinload(Deal.buyer), selectinload(Deal.seller))
    if status:
        stmt = stmt.where(Deal.status == status)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await db.execute(stmt.order_by(Deal.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(d.id),
                "number": d.number,
                "product_name": d.product_name,
                "status": d.status.value,
                "amount_ton": str(from_minor(d.amount_nano, "TON")),
                "commission_ton": str(from_minor(d.commission_nano, "TON")),
                "buyer": d.buyer.username or str(d.buyer.telegram_id) if d.buyer else None,
                "seller": d.seller.username or str(d.seller.telegram_id) if d.seller else None,
                "dispute_reason": d.dispute_reason,
                "confirm_deadline_at": (
                    d.confirm_deadline_at.isoformat() if d.confirm_deadline_at else None
                ),
                "created_at": d.created_at.isoformat(),
            }
            for d in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/deals/{deal_id}/messages")
async def deal_conversation(
    deal_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Вся переписка по сделке.

    Ради этого релей и делался: при разборе спора администрация видит, кто
    что обещал, с точными временами. При форум-топиках эти данные лежали бы в
    Telegram и программно не доставались.
    """
    deal = await db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Сделка не найдена")

    rows = (
        await db.execute(
            select(DealMessage)
            .where(DealMessage.deal_id == deal_id)
            .order_by(DealMessage.created_at)
        )
    ).scalars().all()

    return {
        "deal": {"number": deal.number, "status": deal.status.value,
                 "product_name": deal.product_name},
        "messages": [
            {
                "direction": m.direction.value,
                "text": m.text,
                "media_type": m.media_type,
                # file_id позволяет админу переслать вложение себе командой бота
                "media_file_id": m.media_file_id,
                "delivery_error": m.delivery_error,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ],
    }


@router.post("/deals/{deal_id}/resolve")
async def resolve_dispute(
    deal_id: uuid.UUID,
    payload: DisputeResolution,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Решение по спору: деньги продавцу или возврат покупателю.

    Возврат зачисляется на внутренний баланс покупателя. Выплата наружу —
    отдельное ручное действие через заявку на вывод, чтобы не держать
    приватный ключ горячего кошелька на сервере.
    """
    deal = await db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Сделка не найдена")

    try:
        await deal_service.resolve_dispute(
            db, deal, admin, release=payload.release, comment=payload.comment,
        )
    except deal_service.DealError as e:
        raise HTTPException(status_code=400, detail=str(e))

    verdict = (
        "Спор решён в пользу продавца, деньги перечислены ему."
        if payload.release
        else "Спор решён в пользу покупателя, средства возвращены на его баланс."
    )
    await relay_service.post_system_message(
        db, deal, f"{verdict}\n{payload.comment or ''}".strip(),
    )
    await relay_service.close_chat(db, deal)
    await db.commit()

    return {"status": deal.status.value}
