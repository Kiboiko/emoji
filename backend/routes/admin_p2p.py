"""Админка P2P: модерация заявок, сделки, разбор споров."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models.p2p import (
    Deal, DealMessage, DealStatus, ListingImage, ListingStatus, ProductListing,
    SellerProfile, SellerStatus,
)
from models.product import Product
from models.user import User
from config import settings as app_settings
from services import (
    audit_service, deal_chat_service, deal_service, image_variants, moderation_service,
    settings_service, stock_service,
)
from services.money import from_minor
from utils.auth import require_admin, require_staff

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/p2p", tags=["Admin P2P"])


class ModerationDecision(BaseModel):
    approve: bool
    comment: Optional[str] = Field(None, max_length=1000)


class DisputeResolution(BaseModel):
    # True — деньги продавцу, False — возврат покупателю
    release: bool
    comment: Optional[str] = Field(None, max_length=2000)


class VerificationDecision(BaseModel):
    verified: bool


class PlatformStoreUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)


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
    admin: User = Depends(require_staff),
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
                # С идентификаторами — чтобы модератор мог удалить конкретное фото
                "image_items": [{"id": str(img.id), "url": img.url} for img in l.images],
                "quantity": l.quantity,
                "seller": {
                    "id": str(l.seller.id),
                    "display_name": l.seller.display_name,
                    "avatar_url": l.seller.avatar_url,
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
    admin: User = Depends(require_staff),
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

        # Если товар уже был в каталоге (правка после одобрения), он остаётся
        # снятым: отказ означает, что новый текст показывать нельзя.
        if listing.product_id:
            rejected_product = await db.get(Product, listing.product_id)
            if rejected_product is not None:
                rejected_product.is_active = False

        threshold = await settings_service.get_int(db, "p2p_reject_block_threshold")
        restricted = False
        if seller.rejected_streak >= threshold:
            seller.status = SellerStatus.RESTRICTED
            seller.restricted_until = datetime.utcnow() + timedelta(days=7)
            seller.restriction_reason = (
                f"{seller.rejected_streak} отказа подряд при модерации"
            )
            restricted = True

        audit_service.log_action(
            db, admin, "listing.reject", target_type="listing", target_id=listing.id,
            details={
                "name": listing.name, "seller": seller.display_name,
                "comment": decision.comment, "seller_restricted": restricted,
            },
        )
        await db.commit()
        await _notify_seller(
            db, seller,
            f"Заявка «{listing.name}» отклонена.\n"
            + (f"Причина: {decision.comment}\n" if decision.comment else "")
            + ("\nРазмещение временно ограничено на 7 дней." if restricted else ""),
        )
        return {"status": listing.status.value, "seller_restricted": restricted}

    # --- Одобрение: заводим или обновляем товар в каталоге ---
    try:
        product = await moderation_service.approve_listing(
            db, listing, seller, moderator_id=admin.id, comment=decision.comment,
        )
    except moderation_service.ModerationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit_service.log_action(
        db, admin, "listing.approve", target_type="listing", target_id=listing.id,
        details={"name": listing.name, "seller": seller.display_name, "comment": decision.comment},
    )
    await db.commit()

    await _notify_seller(db, seller, f"Заявка «{listing.name}» одобрена, товар опубликован.")
    return {"status": listing.status.value, "product_id": str(product.id)}


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
    # Магазин площадки сюда не попадает: у него нет владельца, его
    # нельзя заблокировать, и правится он отдельной ручкой
    stmt = (
        select(SellerProfile)
        .options(selectinload(SellerProfile.user))
        .where(SellerProfile.is_platform.is_(False))
    )
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
                "avatar_url": s.avatar_url,
                "username": s.user.username if s.user else None,
                "telegram_id": s.user.telegram_id if s.user else None,
                "status": s.status.value,
                "is_verified": s.is_verified,
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
        # Только товары продавца: подписки тоже висят на нём, но их продажа
        # зависит от состояния канала, а сток у них пустой — «не кончается».
        # Проставить туда ноль значило бы тихо закрыть канал через чужую
        # дверь, и обратно он сам бы не открылся.
        products = (
            await db.execute(
                select(Product).where(
                    Product.owner_user_id == seller.user_id,
                    Product.is_p2p.is_(True),
                )
            )
        ).scalars().all()
        for product in products:
            product.stock = 0

    audit_service.log_action(
        db, admin, "seller.status", target_type="seller", target_id=seller.id,
        details={"store": seller.display_name, "status": payload.status.value,
                 "reason": payload.reason, "restrict_days": payload.restrict_days},
    )
    await db.commit()
    return {"status": seller.status.value}


@router.get("/platform-store")
async def get_platform_store(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Магазин самой площадки.

    Такой же продавец, как остальные, только заполняет его администратор,
    а не владелец. Строка заводится миграцией — если её нет, это сломанная
    база, а не штатный случай.
    """
    store = await _platform_store(db)
    return {
        "id": str(store.id),
        "display_name": store.display_name,
        "description": store.description,
        "avatar_url": store.avatar_url,
        "is_verified": store.is_verified,
    }


@router.patch("/platform-store")
async def update_platform_store(
    payload: PlatformStoreUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    store = await _platform_store(db)

    if payload.display_name is not None:
        name = payload.display_name.strip()
        # Названия магазинов уникальны: два одинаковых в каталоге
        # неразличимы, и покупатель не поймёт, куда он попал
        if name.lower() != store.display_name.lower():
            from routes.p2p import _assert_name_is_free
            await _assert_name_is_free(db, name, exclude_id=store.id)
        store.display_name = name
    if payload.description is not None:
        store.description = payload.description.strip() or None

    await db.commit()
    return {"display_name": store.display_name, "description": store.description}


@router.post("/platform-store/avatar")
async def upload_platform_store_avatar(
    image: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Логотип площадки — те же проверки, что у логотипа продавца."""
    from routes.p2p import _save_listing_image

    store = await _platform_store(db)
    store.avatar_url = await _save_listing_image(image, subdir="stores")
    await db.commit()
    return {"avatar_url": store.avatar_url}


async def _platform_store(db: AsyncSession) -> SellerProfile:
    store = (
        await db.execute(
            select(SellerProfile).where(SellerProfile.is_platform.is_(True))
        )
    ).scalars().first()
    if store is None:
        raise HTTPException(
            status_code=500,
            detail="Магазин площадки не заведён — не накачена миграция b1c2d3e4f5a6",
        )
    return store


@router.post("/sellers/{seller_id}/verify")
async def set_seller_verified(
    seller_id: uuid.UUID,
    decision: VerificationDecision,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Ставит или снимает галочку проверенного продавца.

    Отдельно от статуса: активный продавец — это «не заблокирован», галочка —
    «площадка подтвердила, кто он». Покупатель по ней и отличает случайного
    продавца от того, за кого площадка ручается.
    """
    seller = await db.get(SellerProfile, seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Продавец не найден")

    seller.is_verified = decision.verified
    audit_service.log_action(
        db, admin, "seller.verify" if decision.verified else "seller.unverify",
        target_type="seller", target_id=seller.id, details={"store": seller.display_name},
    )
    await db.commit()
    return {"is_verified": seller.is_verified}


# ---------------------------------------------------------------------------
# Сделки и споры
# ---------------------------------------------------------------------------

@router.get("/deals")
async def list_deals(
    status: Optional[DealStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_staff),
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
    admin: User = Depends(require_staff),
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

    store = (
        await db.execute(select(SellerProfile).where(SellerProfile.user_id == deal.seller_id))
    ).scalars().first()

    return {
        "deal": {
            "number": deal.number,
            "status": deal.status.value,
            "product_name": deal.product_name,
            "store": store.display_name if store else None,
            "amount_ton": str(from_minor(deal.amount_nano, "TON")),
            "dispute_reason": deal.dispute_reason,
            # Модератор пишет в переписку, пока сделка не завершена
            "can_write": deal.status not in deal_service.FINAL,
        },
        "messages": [deal_chat_service.admin_message_dto(m) for m in rows],
    }


class ModeratorMessage(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.post("/deals/{deal_id}/messages")
async def moderator_message(
    deal_id: uuid.UUID,
    payload: ModeratorMessage,
    admin: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """
    Модератор пишет в переписку сделки.

    Стороны видят это сообщение у себя в чате с пометкой «Модератор
    площадки» и получают уведомление бота, как о любом другом сообщении.
    """
    deal = await db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    if deal.status in deal_service.FINAL:
        raise HTTPException(status_code=400, detail="Сделка завершена, переписка закрыта")

    try:
        message = await deal_chat_service.post_moderator(db, deal, admin, payload.text)
    except deal_chat_service.ChatError as e:
        raise HTTPException(status_code=400, detail=str(e))

    audit_service.log_action(
        db, admin, "deal.message", target_type="deal", target_id=deal.id,
        details={"number": deal.number, "text": payload.text[:300]},
    )
    await db.commit()
    await deal_chat_service.push_message(deal, message)
    return deal_chat_service.admin_message_dto(message)


@router.post("/deals/{deal_id}/resolve")
async def resolve_dispute(
    deal_id: uuid.UUID,
    payload: DisputeResolution,
    admin: User = Depends(require_staff),
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

    message = await deal_chat_service.post_system(
        db, deal, "resolved", deal_chat_service.resolved_text(payload.release, payload.comment),
    )
    deal_chat_service.close_chat(deal)
    if not payload.release and deal.product_id:
        # Возврат освобождает проданную единицу — она снова в продаже
        await stock_service.refresh_p2p_stock(db, deal.product_id)
    audit_service.log_action(
        db, admin, "deal.resolve", target_type="deal", target_id=deal.id,
        details={
            "number": deal.number,
            "decision": "деньги продавцу" if payload.release else "возврат покупателю",
            "comment": payload.comment,
        },
    )
    await db.commit()
    await deal_chat_service.push_message(deal, message)
    await deal_chat_service.push_deal(db, deal)

    return {"status": deal.status.value}


# ---------------------------------------------------------------------------
# Удаление фото
# ---------------------------------------------------------------------------

def _remove_files(urls: list[str]) -> None:
    """Файлы удаляются ПОСЛЕ коммита: откат не должен оставить запись без файла."""
    for url in urls:
        try:
            image_variants.remove(Path(app_settings.UPLOAD_DIR), url)
        except Exception as e:
            logger.warning("[ADMIN] Файл %s не удалён: %s", url, e)


@router.delete("/listings/{listing_id}/images/{image_id}")
async def delete_listing_photo(
    listing_id: uuid.UUID,
    image_id: uuid.UUID,
    admin: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """
    Модератор убирает фото из объявления.

    Фото исчезает и из заявки, и из карточки товара в каталоге, и с диска:
    нарушающая картинка не должна оставаться доступной по прямой ссылке.
    Повторной проверки не требуется — решение принял сам модератор.
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

    image = next((i for i in listing.images if i.id == image_id), None)
    if image is None:
        raise HTTPException(status_code=404, detail="Фото не найдено")

    url = image.url
    remaining = [i.url for i in listing.images if i.id != image_id]

    if listing.product_id:
        product = await db.get(Product, listing.product_id)
        if product is not None:
            product.images = remaining
            if product.image_url == url:
                product.image_url = remaining[0] if remaining else moderation_service.PLACEHOLDER_IMAGE

    await db.delete(image)
    audit_service.log_action(
        db, admin, "photo.delete", target_type="listing", target_id=listing.id,
        details={"kind": "listing_image", "name": listing.name, "url": url,
                 "seller": listing.seller.display_name},
    )
    await db.commit()

    # Тот же файл мог быть у другого объявления — тогда он остаётся
    shared = (
        await db.execute(select(func.count(ListingImage.id)).where(ListingImage.url == url))
    ).scalar() or 0
    if not shared:
        _remove_files([url])

    await _notify_seller(
        db, listing.seller,
        f"Модератор удалил фото из объявления «{listing.name}». "
        f"Если нужно, добавьте другое фото.",
    )
    return {"deleted": True, "remaining": len(remaining)}


@router.delete("/sellers/{seller_id}/avatar")
async def delete_seller_avatar(
    seller_id: uuid.UUID,
    admin: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """Убирает логотип магазина — пользователь загрузил что-то недопустимое."""
    seller = await db.get(SellerProfile, seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Продавец не найден")
    if seller.is_platform:
        raise HTTPException(status_code=400, detail="Логотип площадки меняется в её настройках")
    if not seller.avatar_url:
        raise HTTPException(status_code=400, detail="У магазина нет логотипа")

    url = seller.avatar_url
    seller.avatar_url = None
    audit_service.log_action(
        db, admin, "photo.delete", target_type="seller", target_id=seller.id,
        details={"kind": "store_avatar", "store": seller.display_name, "url": url},
    )
    await db.commit()

    _remove_files([url])
    await _notify_seller(
        db, seller,
        "Модератор удалил логотип вашего магазина. Загрузите другой в настройках магазина.",
    )
    return {"deleted": True}
