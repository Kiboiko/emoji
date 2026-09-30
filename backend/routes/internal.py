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
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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


# ---------------------------------------------------------------------------
# Релей-чат сделок
# ---------------------------------------------------------------------------

class RelayIn(BaseModel):
    telegram_user_id: int
    # Сырое сообщение Telegram: нужно целиком, потому что copyMessage
    # оперирует message_id, а тип вложения определяется по составу полей
    message: dict


@router.post("/relay", dependencies=[Depends(require_internal_token)])
async def relay_incoming(payload: RelayIn, db: AsyncSession = Depends(get_db)):
    """
    Сообщение пользователя боту.

    Бот больше не пересылает переписку по сделкам: при двух открытых сделках
    он переспрашивал, кому адресовано сообщение, и приходилось отвечать
    реплаем. Переписка теперь в приложении, а здесь — кнопки, открывающие
    чат каждой открытой сделки. Само сообщение никуда не отправляется, и
    человеку об этом говорится прямо.

    Ответ отправляет бэкенд, а не бот: кнопки открывают мини-апп, и адрес
    приложения знает бэкенд. Пустой reply говорит боту промолчать.
    """
    from services import deal_chat_service as chat
    from services.telegram_service import telegram_service

    user = (
        await db.execute(select(User).where(User.telegram_id == payload.telegram_user_id))
    ).scalars().first()
    if user is None:
        return {"reply": "Вы ещё не пользовались магазином. Откройте его кнопкой ниже."}

    deals = await chat.open_deals_for(db, user)
    if not deals:
        return {"reply": "У вас нет активных сделок."}

    rows = []
    for deal in deals[:8]:
        keyboard = chat.open_chat_keyboard(deal, f"№{deal.number} · {deal.product_name[:40]}")
        if keyboard is None:
            break
        rows.append(keyboard["inline_keyboard"][0])

    text = (
        "Переписка по сделкам теперь в приложении: там видно, по какой сделке "
        "вы пишете, и можно отправить фото. Это сообщение никому не отправлено."
    )
    if not rows:
        return {"reply": text + "\nОткройте магазин и зайдите в «Мои сделки»."}

    try:
        await telegram_service.send_message(
            user.telegram_id,
            text + ("\nВыберите сделку:" if len(rows) > 1 else ""),
            parse_mode=None,
            reply_markup={"inline_keyboard": rows},
        )
    except Exception as e:
        logger.warning("[INTERNAL] Не удалось отправить кнопки чатов: %s", e)
        return {"reply": text}
    return {"reply": None}


class DealActionIn(BaseModel):
    telegram_user_id: int
    deal_number: int
    # delivered | confirm | dispute
    action: str
    reason: str | None = None


@router.post("/deal-action", dependencies=[Depends(require_internal_token)])
async def deal_action(payload: DealActionIn, db: AsyncSession = Depends(get_db)):
    """
    Кнопки под старыми сообщениями бота: «отправил», «подтверждаю», «спор».

    Новые уведомления таких кнопок не несут — действия теперь в карточке
    сделки над перепиской. Эти работают для сообщений, уже лежащих в чатах.
    """
    from models.p2p import Deal
    from services import deal_chat_service as chat
    from services import deal_service

    user = (
        await db.execute(select(User).where(User.telegram_id == payload.telegram_user_id))
    ).scalars().first()
    if user is None:
        return {"reply": "Пользователь не найден"}

    deal = (
        await db.execute(select(Deal).where(Deal.number == payload.deal_number))
    ).scalars().first()
    if deal is None or chat.role_of(deal, user) is None:
        return {"reply": "Сделка не найдена"}

    try:
        if payload.action == "delivered":
            await deal_service.mark_delivered(db, deal, user)
            message = await chat.post_system(db, deal, "ship", chat.ship_text(deal), actor=user)
            reply = "Отмечено. Ждём подтверждения покупателя."

        elif payload.action == "confirm":
            await deal_service.confirm_receipt(db, deal, user)
            message = await chat.post_system(db, deal, "done", chat.DONE_TEXT, actor=user)
            chat.close_chat(deal)
            reply = "Спасибо! Деньги перечислены продавцу."

        elif payload.action == "dispute":
            reason = payload.reason or "не указана"
            await deal_service.open_dispute(db, deal, user, reason)
            message = await chat.post_system(
                db, deal, "dispute", chat.dispute_text(chat.role_of(deal, user), reason),
                actor=user,
            )
            reply = "Спор открыт, модератор подключится к переписке в приложении."

        else:
            return {"reply": "Неизвестное действие"}

    except deal_service.DealError as e:
        await db.rollback()
        return {"reply": str(e)}

    await db.commit()
    await chat.push_message(deal, message)
    await chat.push_deal(db, deal)
    return {"reply": reply}


class ModerationIn(BaseModel):
    telegram_user_id: int
    listing_id: uuid.UUID
    approve: bool


@router.post("/moderate-listing", dependencies=[Depends(require_internal_token)])
async def moderate_listing_from_bot(
    payload: ModerationIn, db: AsyncSession = Depends(get_db),
):
    """
    Модерация заявки кнопкой в Telegram.

    Права проверяются здесь, а не в боте: общий секрет подтверждает только то,
    что запрос пришёл от нашего бота, но не то, что кнопку нажал администратор.
    Уведомления уходят в админский чат, а он может быть групповым — там кнопку
    видит и может нажать любой участник.

    Отказ кнопкой не поддерживается намеренно: причину отказа в callback не
    введёшь, а отказ без причины продавец не может исправить, и он же двигает
    счётчик отказов подряд к автоматическому ограничению.
    """
    from models.p2p import ListingStatus, ProductListing

    admin = (
        await db.execute(select(User).where(User.telegram_id == payload.telegram_user_id))
    ).scalars().first()
    if admin is None or not admin.is_admin:
        return {"reply": "Недостаточно прав"}

    if not payload.approve:
        # open_admin — явный флаг для бота, а не разбор текста reply: строка
        # могла бы измениться, и сравнение "похоже на нужную фразу" однажды
        # молча перестало бы совпадать.
        return {
            "reply": "Для отказа откройте админку — нужна причина, её увидит продавец",
            "open_admin": True,
        }

    listing = (
        await db.execute(
            select(ProductListing)
            .options(selectinload(ProductListing.images), selectinload(ProductListing.seller))
            .where(ProductListing.id == payload.listing_id)
        )
    ).scalars().first()
    if listing is None:
        return {"reply": "Заявка не найдена"}
    if listing.status != ListingStatus.PENDING:
        # Обычный случай: двое администраторов нажали одну и ту же кнопку
        return {"reply": f"Заявка уже обработана (статус: {listing.status.value})"}

    from routes.admin_p2p import moderate_listing, ModerationDecision

    result = await moderate_listing(
        listing.id, ModerationDecision(approve=True), admin=admin, db=db,
    )
    return {"reply": f"Товар «{listing.name}» опубликован", "status": result["status"]}
