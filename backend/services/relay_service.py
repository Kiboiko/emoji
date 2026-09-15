"""
Релей-чат сделки: бот пересылает сообщения между личками покупателя и продавца.

Так работает P2P в TG Wallet. Групп и топиков нет вообще — каждый пишет боту,
бот доставляет второй стороне.

Два принципиальных решения:

1. ПЕРЕСЫЛКА ЧЕРЕЗ copyMessage, а не forwardMessage. Копия приходит без
   пометки «переслано от», поэтому стороны не видят username и профиль друг
   друга. Это защищает сделку от увода мимо escrow: договориться напрямую,
   минуя платформу, не получится.

2. ВСЁ СОХРАНЯЕТСЯ В БД. Переписка — единственное доказательство при разборе
   спора. Медиа храним как file_id: файлы хостит Telegram, а file_id остаётся
   валидным и позволяет админу переслать вложение себе.

Маршрутизация («в какую сделку это сообщение») — главная сложность, см.
resolve_deal().
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.p2p import Deal, DealMessage, DealStatus, MessageDirection
from models.user import User
from services.telegram_service import TelegramApiError, _call

logger = logging.getLogger(__name__)

# Сделки, в которых переписка ещё разрешена
OPEN_STATUSES = (
    DealStatus.PAID_ESCROW,
    DealStatus.CHAT_OPENED,
    DealStatus.DELIVERED_CLAIMED,
    DealStatus.DISPUTED,
)

# Типы вложений, которые умеет пересылать copyMessage
MEDIA_FIELDS = (
    "photo", "document", "video", "voice", "audio",
    "animation", "sticker", "video_note",
)


class RelayError(Exception):
    pass


class CounterpartUnavailable(RelayError):
    """Контрагент заблокировал бота или недоступен."""


# ---------------------------------------------------------------------------
# Маршрутизация
# ---------------------------------------------------------------------------

async def open_deals_for(db: AsyncSession, user: User) -> list[Deal]:
    return (
        await db.execute(
            select(Deal)
            .where(
                or_(Deal.buyer_id == user.id, Deal.seller_id == user.id),
                Deal.status.in_(OPEN_STATUSES),
                Deal.chat_closed.is_(False),
            )
            .order_by(Deal.created_at.desc())
        )
    ).scalars().all()


async def resolve_deal(
    db: AsyncSession, user: User, *, reply_to_message_id: int | None = None
) -> tuple[Deal | None, str | None]:
    """
    Определяет, в какую сделку адресовано сообщение.

    Порядок:
      1. Reply на сообщение контрагента — самый надёжный признак, перекрывает
         всё остальное. Ищем по delivered_message_id.
      2. Активная сделка пользователя, если она ещё открыта.
      3. Единственная открытая сделка — очевидный случай.
      4. Несколько открытых и активная не выбрана — отказываемся угадывать.
         Отправить сообщение не тому человеку хуже, чем переспросить.

    Возвращает (сделка, текст ошибки для пользователя).
    """
    if reply_to_message_id:
        message = (
            await db.execute(
                select(DealMessage).where(
                    DealMessage.delivered_message_id == reply_to_message_id
                )
            )
        ).scalars().first()
        if message is not None:
            deal = await db.get(Deal, message.deal_id)
            if deal and _is_participant(deal, user):
                return deal, None

    deals = await open_deals_for(db, user)

    if not deals:
        return None, "У вас нет активных сделок."

    if user.active_deal_id:
        active = next((d for d in deals if d.id == user.active_deal_id), None)
        if active is not None:
            return active, None

    if len(deals) == 1:
        return deals[0], None

    listing = "\n".join(f"  №{d.number} — {d.product_name}" for d in deals[:10])
    return None, (
        "У вас несколько активных сделок, непонятно, кому адресовать сообщение:\n"
        f"{listing}\n\n"
        "Ответьте (reply) на сообщение собеседника или выберите сделку "
        "в приложении."
    )


def _is_participant(deal: Deal, user: User) -> bool:
    return user.id in (deal.buyer_id, deal.seller_id)


async def set_active_deal(db: AsyncSession, user: User, deal: Deal) -> None:
    if not _is_participant(deal, user):
        raise RelayError("Пользователь не участник сделки")
    user.active_deal_id = deal.id


# ---------------------------------------------------------------------------
# Пересылка
# ---------------------------------------------------------------------------

def extract_media(message: dict) -> tuple[str | None, str | None]:
    """Тип вложения и его file_id из апдейта Telegram."""
    for field in MEDIA_FIELDS:
        value = message.get(field)
        if not value:
            continue
        # photo приходит списком размеров, берём самый крупный
        if field == "photo":
            return "photo", value[-1]["file_id"]
        return field, value.get("file_id")
    return None, None


def _header(deal: Deal, sender_is_buyer: bool) -> str:
    role = "Покупатель" if sender_is_buyer else "Продавец"
    return f"Сделка №{deal.number} · {deal.product_name}\n{role}:"


async def relay_message(
    db: AsyncSession,
    *,
    deal: Deal,
    sender: User,
    message: dict,
) -> DealMessage:
    """
    Доставляет сообщение второй стороне и сохраняет его в БД.

    Запись создаётся ДО отправки: если доставка не удалась, сообщение всё
    равно останется в истории с текстом ошибки. Для разбора спора важно
    видеть и то, что человек пытался сказать.
    """
    if deal.chat_closed or deal.status not in OPEN_STATUSES:
        raise RelayError(f"Чат по сделке №{deal.number} закрыт.")

    sender_is_buyer = sender.id == deal.buyer_id
    recipient_id = deal.seller_id if sender_is_buyer else deal.buyer_id
    recipient = await db.get(User, recipient_id)
    if recipient is None:
        raise RelayError("Собеседник не найден.")

    media_type, file_id = extract_media(message)
    text = message.get("text") or message.get("caption")

    record = DealMessage(
        id=uuid.uuid4(),
        deal_id=deal.id,
        direction=(
            MessageDirection.BUYER_TO_SELLER if sender_is_buyer
            else MessageDirection.SELLER_TO_BUYER
        ),
        sender_id=sender.id,
        text=text,
        media_type=media_type,
        media_file_id=file_id,
        source_message_id=message.get("message_id"),
    )
    db.add(record)
    await db.flush()

    header = _header(deal, sender_is_buyer)

    try:
        if media_type or message.get("message_id"):
            # copyMessage тянет любой тип вложения одним вызовом и, в отличие
            # от forwardMessage, не показывает отправителя
            result = await _call("copyMessage", {
                "chat_id": recipient.telegram_id,
                "from_chat_id": sender.telegram_id,
                "message_id": message["message_id"],
                "caption": f"{header}\n{text}" if text else header,
            })
        else:
            result = await _call("sendMessage", {
                "chat_id": recipient.telegram_id,
                "text": f"{header}\n{text}",
            })
        record.delivered_message_id = result.get("message_id")

    except TelegramApiError as e:
        record.delivery_error = e.description
        logger.error(
            "[RELAY] Сделка #%s: не доставлено %s -> %s: %s",
            deal.number, sender.telegram_id, recipient.telegram_id, e.description,
        )
        # 403 = получатель заблокировал бота. Отправителю надо сказать честно,
        # иначе он будет думать, что его игнорируют.
        if e.error_code == 403 or "blocked" in e.description.lower():
            raise CounterpartUnavailable(
                "Собеседник заблокировал бота и не получит сообщение. "
                "Обратитесь в поддержку."
            )
        raise RelayError("Не удалось доставить сообщение. Попробуйте позже.")

    # Первое сообщение переводит сделку в «чат открыт»
    if deal.status == DealStatus.PAID_ESCROW:
        deal.status = DealStatus.CHAT_OPENED

    return record


async def post_system_message(db: AsyncSession, deal: Deal, text: str) -> None:
    """
    Системное сообщение платформы обеим сторонам.

    Падает в тот же поток, что и переписка, чтобы у сторон складывалась
    цельная картина: «оплата получена», «продавец отметил отправку»,
    «открыт спор».
    """
    from services.telegram_service import telegram_service

    body = f"Сделка №{deal.number} · {deal.product_name}\n{text}"

    db.add(DealMessage(
        id=uuid.uuid4(),
        deal_id=deal.id,
        direction=MessageDirection.SYSTEM,
        sender_id=None,
        text=text,
    ))

    for user_id in (deal.buyer_id, deal.seller_id):
        user = await db.get(User, user_id)
        if not user:
            continue
        try:
            await telegram_service.send_message(user.telegram_id, body, parse_mode=None)
        except Exception as e:
            logger.warning("[RELAY] Системное сообщение не доставлено %s: %s", user_id, e)


async def close_chat(db: AsyncSession, deal: Deal) -> None:
    """
    Закрывает чат на запись. История остаётся читаемой — так согласовано.

    Активную сделку у обеих сторон сбрасываем, иначе следующее сообщение
    улетит в закрытый чат и вернётся ошибкой.
    """
    deal.chat_closed = True

    for user_id in (deal.buyer_id, deal.seller_id):
        user = await db.get(User, user_id)
        if user and user.active_deal_id == deal.id:
            user.active_deal_id = None
