"""
Сделки глазами их участников: список, переписка, действия.

Переписка идёт здесь, в приложении, а не через бота: у каждой сделки свой
чат, и сообщение не нужно адресовать реплаем. Бот только присылает
уведомление с кнопкой, открывающей нужный чат (services/deal_chat_service).

Модерация и разбор споров — в routes/admin_p2p.py.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from config import settings
from database import get_db
from models.p2p import Deal, DealMessage
from models.user import User
from services import deal_chat_service as chat
from services import deal_media, deal_service, stock_service
from services.money import format_ton_short
from utils.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/p2p", tags=["Deals"])

# Переписка по сделке редко длиннее сотни сообщений; больше этого за раз
# отдавать незачем — чат показывает хвост
HISTORY_LIMIT = 300


class MessageIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=chat.MAX_TEXT)


class DisputeOpen(BaseModel):
    # Причина выбирается кнопкой («Товар не получен», «Другое»), поэтому
    # короткая — это нормально; подробности идут следом через точку
    reason: str = Field(..., min_length=3, max_length=500)


async def _participant_deal(db: AsyncSession, deal_id: uuid.UUID, user: User) -> Deal:
    deal = await db.get(Deal, deal_id)
    if deal is None or chat.role_of(deal, user) is None:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    return deal


async def _reviewed_ids(db: AsyncSession, user: User, deal_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Сделки, по которым покупатель уже оставил отзыв — одним запросом на список."""
    if not deal_ids:
        return set()
    from models.review import Review

    rows = (
        await db.execute(
            select(Review.deal_id).where(Review.user_id == user.id, Review.deal_id.in_(deal_ids))
        )
    ).scalars().all()
    return {r for r in rows if r is not None}


async def _dto(db: AsyncSession, deal: Deal, user: User) -> dict:
    reviewed = await _reviewed_ids(db, user, [deal.id])
    return (await chat.deal_dtos(db, [deal], user, reviewed=reviewed))[0]


# ---------------------------------------------------------------------------
# Список и карточка
# ---------------------------------------------------------------------------

@router.get("/deals")
async def my_deals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сделки пользователя — свежая переписка сверху, как в мессенджере."""
    deals = (
        await db.execute(
            select(Deal)
            .where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id))
            .order_by(Deal.created_at.desc())
        )
    ).scalars().all()

    reviewed = await _reviewed_ids(db, user, [d.id for d in deals])
    rows = await chat.deal_dtos(db, list(deals), user, reviewed=reviewed)
    rows.sort(key=lambda d: d["last_activity_at"] or "", reverse=True)
    return rows


@router.get("/deals/unread")
async def unread(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Непрочитанное по сделкам — для значков в меню.

    Отдельно от списка: значок нужен на каждом экране с первой секунды, а
    список сделок с фото и последними сообщениями грузить ради него незачем.
    """
    counts = await chat.unread_counts(db, user)
    return {
        "total": sum(counts.values()),
        "deals": {str(deal_id): n for deal_id, n in counts.items()},
    }


@router.get("/deals/{deal_id}")
async def deal_card(
    deal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Одна сделка — чат открывают и по ссылке из уведомления, минуя список.

    В отличие от списка, здесь ещё и подробности товара для страницы сделки
    в «Мои сделки»: описание, все фото, количество и магазин.
    """
    deal = await _participant_deal(db, deal_id, user)
    card = await _dto(db, deal, user)
    card["details"] = await _details(db, deal, card["role"])
    return card


async def _details(db: AsyncSession, deal: Deal, role: str) -> dict:
    """
    Товар таким, каким его купили: из снимка позиции заказа, а не из
    текущей карточки — продавец мог сменить описание или снять товар.
    Магазин — только покупателю: продавец о своём и так знает.
    """
    from models.order import OrderItem
    from models.p2p import SellerProfile

    item = await db.get(OrderItem, deal.order_item_id) if deal.order_item_id else None
    snapshot = (item.product_snapshot if item else None) or {}
    images = snapshot.get("images") or ([snapshot["image_url"]] if snapshot.get("image_url") else [])

    store = None
    if role == "buyer":
        profile = (
            await db.execute(select(SellerProfile).where(SellerProfile.user_id == deal.seller_id))
        ).scalars().first()
        if profile is not None:
            store = {
                "id": str(profile.id),
                "rating": profile.rating,
                "rating_count": profile.rating_count,
                "deals_completed": profile.deals_completed,
            }

    return {
        "description": snapshot.get("description_ru"),
        "description_en": snapshot.get("description_en"),
        "name_en": snapshot.get("name_en"),
        "images": images,
        "quantity": item.quantity if item else 1,
        "store": store,
    }


# ---------------------------------------------------------------------------
# Переписка
# ---------------------------------------------------------------------------

@router.get("/deals/{deal_id}/messages")
async def deal_messages(
    deal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deal = await _participant_deal(db, deal_id, user)
    role = chat.role_of(deal, user)

    newest = (
        await db.execute(
            select(DealMessage)
            .where(DealMessage.deal_id == deal.id)
            .order_by(DealMessage.created_at.desc())
            .limit(HISTORY_LIMIT)
        )
    ).scalars().all()

    seen = chat.read_at(deal, chat.other(role))

    # Срок хранения закрытой переписки вышел — у сторон её больше нет
    if chat.chat_expired(deal, await chat.retention_days(db)):
        return {"messages": [], "counterpart_read_at": chat.iso(seen), "expired": True}

    return {
        "messages": [chat.message_dto(m, role, seen) for m in reversed(newest)],
        "counterpart_read_at": chat.iso(seen),
        "expired": False,
    }


async def _deliver(db: AsyncSession, deal: Deal, message: DealMessage) -> None:
    """Коммит и рассылка сторонам — строго в этом порядке."""
    await db.commit()
    await chat.push_message(deal, message)


@router.post("/deals/{deal_id}/messages")
async def send_message(
    deal_id: uuid.UUID,
    payload: MessageIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deal = await _participant_deal(db, deal_id, user)
    try:
        message = await chat.post_message(db, deal, user, text=payload.text)
    except chat.ChatError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await _deliver(db, deal, message)
    role = chat.role_of(deal, user)
    return chat.message_dto(message, role, chat.read_at(deal, chat.other(role)))


@router.post("/deals/{deal_id}/photos")
async def send_photo(
    deal_id: uuid.UUID,
    image: UploadFile = File(...),
    caption: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deal = await _participant_deal(db, deal_id, user)
    # До записи файла: закрытому чату фото на диске ни к чему
    if not chat.is_open(deal):
        raise HTTPException(
            status_code=400, detail="Сделка завершена. Писать больше нельзя, история сохранена.",
        )

    content = await image.read(settings.DEAL_MEDIA_MAX_SIZE + 1)
    try:
        # Pillow держит процессор: в потоке, чтобы не вставал весь сервер
        name = await run_in_threadpool(deal_media.save_photo, content, deal.id)
    except deal_media.MediaError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        message = await chat.post_message(db, deal, user, text=caption, media_path=name)
    except chat.ChatError as e:
        (deal_media.media_dir() / name).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(e))

    await _deliver(db, deal, message)
    role = chat.role_of(deal, user)
    return chat.message_dto(message, role, chat.read_at(deal, chat.other(role)))


@router.post("/deals/{deal_id}/read")
async def mark_read(
    deal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Переписка прочитана до текущего момента: счётчик в ноль, у собеседника — двойные галочки."""
    deal = await _participant_deal(db, deal_id, user)
    seen = chat.mark_read(deal, user)
    await db.commit()
    await chat.push_read(deal, chat.role_of(deal, user))
    return {"read_at": chat.iso(seen)}


@router.get("/deal-media/{name}")
async def deal_media_file(
    name: str,
    e: int = Query(...),
    s: str = Query(..., max_length=64),
):
    """
    Фото из переписки по подписанной ссылке.

    Без заголовка авторизации: картинку грузит тег img. Доступ доказывает
    подпись, а выдаёт её только эндпоинт переписки, проверивший участника.
    """
    try:
        path = deal_media.resolve(name, e, s)
    except deal_media.MediaError:
        raise HTTPException(status_code=404, detail="Нет такого файла")
    return FileResponse(
        path, media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=21600"},
    )


# ---------------------------------------------------------------------------
# Действия по сделке
# ---------------------------------------------------------------------------

async def _after_action(db: AsyncSession, deal: Deal, message: DealMessage) -> None:
    await db.commit()
    await chat.push_message(deal, message)
    await chat.push_deal(db, deal)


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

    message = await chat.post_system(db, deal, "ship", chat.ship_text(deal), actor=user)
    await _after_action(db, deal, message)
    return await _dto(db, deal, user)


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

    message = await chat.post_system(db, deal, "done", chat.DONE_TEXT, actor=user)
    chat.close_chat(deal)
    await _after_action(db, deal, message)
    return await _dto(db, deal, user)


@router.post("/deals/{deal_id}/refund")
async def refund(
    deal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Продавец сам возвращает деньги — сразу, без спора и модератора.

    Вся сумма уходит на баланс покупателя, сделка закрывается, проданная
    единица снова в продаже.
    """
    deal = await _participant_deal(db, deal_id, user)
    try:
        await deal_service.refund_by_seller(db, deal, user)
    except deal_service.DealError as e:
        raise HTTPException(status_code=400, detail=str(e))

    message = await chat.post_system(db, deal, "refund", chat.refund_text(deal), actor=user)
    if deal.product_id:
        await stock_service.refresh_p2p_stock(db, deal.product_id)
    await _after_action(db, deal, message)
    return await _dto(db, deal, user)


@router.post("/deals/{deal_id}/dispute")
async def open_dispute(
    deal_id: uuid.UUID,
    payload: DisputeOpen,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deal = await _participant_deal(db, deal_id, user)
    reason = payload.reason.strip()
    try:
        await deal_service.open_dispute(db, deal, user, reason)
    except deal_service.DealError as e:
        raise HTTPException(status_code=400, detail=str(e))

    message = await chat.post_system(
        db, deal, "dispute", chat.dispute_text(chat.role_of(deal, user), reason), actor=user,
    )
    await _after_action(db, deal, message)

    from services.telegram_service import telegram_service

    # Кнопка-ссылка, а не действие: решение по спору требует прочитать
    # переписку, и одобрить его в один тап нельзя — деньги уходят необратимо.
    # Telegram принимает только https, поэтому на локальном http кнопку не
    # добавляем: с http-ссылкой он отклонит всё сообщение целиком.
    admin_url = f"{settings.SITE_URL.rstrip('/')}/admin/deals"
    keyboard = (
        {"inline_keyboard": [[{"text": "Открыть в админке", "url": admin_url}]]}
        if admin_url.startswith("https://") else None
    )

    for chat_id in telegram_service.admin_chat_ids:
        try:
            await telegram_service.send_message(
                chat_id,
                f"Открыт спор по сделке #{deal.number}\n"
                f"Товар: {deal.product_name}\n"
                f"Сумма: {format_ton_short(deal.amount_nano)}\n"
                f"Причина: {reason[:300]}",
                parse_mode=None,
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.warning("[DEALS] Не удалось уведомить о споре: %s", e)

    return await _dto(db, deal, user)
