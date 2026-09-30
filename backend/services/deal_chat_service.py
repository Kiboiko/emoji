"""
Переписка по сделке в приложении.

Раньше переписка шла через бота: он копировал сообщения между личками сторон
и угадывал, к какой сделке относится сообщение. При двух открытых сделках
бот переспрашивал, и отвечать приходилось реплаем. Теперь у каждой сделки своя
переписка в мини-аппе, а бот только присылает уведомление с кнопкой, которая
открывает нужный чат.

Что осталось прежним, и почему:

  * стороны не видят друг друга: покупатель видит название магазина,
    продавец — «Покупатель». Договориться мимо escrow так не выйдет;
  * вся переписка хранится в базе — это доказательство при разборе спора.
    Модератор пишет в тот же чат и видит историю вместе с фото.

Прочитанность хранится на сделке одной отметкой времени на сторону, а не
флагом у каждого сообщения: сторон всегда две, и «прочитано всё до момента X»
даёт и счётчик непрочитанного, и двойные галочки у собеседника.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.order import OrderItem
from models.p2p import Deal, DealMessage, DealStatus, MessageDirection, SellerProfile
from models.user import User
from services import deal_media
from services.money import format_amount, from_minor
from utils.websockets import manager

logger = logging.getLogger(__name__)

# Сделки, в которых переписка ещё разрешена
OPEN_STATUSES = (
    DealStatus.PAID_ESCROW,
    DealStatus.CHAT_OPENED,
    DealStatus.DELIVERED_CLAIMED,
    DealStatus.DISPUTED,
)

MAX_TEXT = 2000

# Защита от флуда: столько сообщений в минуту хватает любой живой переписке
FLOOD_LIMIT = 30
FLOOD_WINDOW = timedelta(seconds=60)

OWN_DIRECTION = {
    "buyer": MessageDirection.BUYER_TO_SELLER,
    "seller": MessageDirection.SELLER_TO_BUYER,
}
AUTHOR = {
    MessageDirection.BUYER_TO_SELLER: "buyer",
    MessageDirection.SELLER_TO_BUYER: "seller",
    MessageDirection.SYSTEM: "system",
    MessageDirection.MODERATOR: "moderator",
}

_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
# Даты в текстах сообщений — по Москве: время в базе в UTC, и срок, истекающий
# в 23:00 по UTC, у покупателя из Москвы наступает уже на следующий день
_TEXT_TZ = timedelta(hours=3)


class ChatError(Exception):
    pass


def utcnow() -> datetime:
    return datetime.utcnow()


def iso(value: datetime | None) -> str | None:
    """Время в UTC с явной «Z»: без неё браузер прочёл бы его как местное."""
    if value is None:
        return None
    return value.isoformat(timespec="milliseconds") + "Z"


def ru_date(value: datetime) -> str:
    local = value + _TEXT_TZ
    return f"{local.day} {_MONTHS[local.month - 1]}"


# ---------------------------------------------------------------------------
# Кто есть кто
# ---------------------------------------------------------------------------

def role_of(deal: Deal, user: User) -> str | None:
    if user.id == deal.buyer_id:
        return "buyer"
    if user.id == deal.seller_id:
        return "seller"
    return None


def other(role: str) -> str:
    return "seller" if role == "buyer" else "buyer"


def party_id(deal: Deal, role: str) -> uuid.UUID:
    return deal.buyer_id if role == "buyer" else deal.seller_id


def is_open(deal: Deal) -> bool:
    return deal.status in OPEN_STATUSES and not deal.chat_closed


def read_at(deal: Deal, role: str) -> datetime | None:
    return getattr(deal, f"{role}_read_at")


def _mark_seen(deal: Deal, role: str, when: datetime) -> None:
    current = read_at(deal, role)
    if current is None or when > current:
        setattr(deal, f"{role}_read_at", when)


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


# ---------------------------------------------------------------------------
# Сообщения
# ---------------------------------------------------------------------------

async def _assert_not_flooding(db: AsyncSession, sender: User) -> None:
    recent = (
        await db.execute(
            select(func.count())
            .select_from(DealMessage)
            .where(
                DealMessage.sender_id == sender.id,
                DealMessage.created_at >= utcnow() - FLOOD_WINDOW,
            )
        )
    ).scalar() or 0
    if recent >= FLOOD_LIMIT:
        raise ChatError("Слишком много сообщений подряд. Подождите минуту.")


async def post_message(
    db: AsyncSession,
    deal: Deal,
    sender: User,
    *,
    text: str | None = None,
    media_path: str | None = None,
) -> DealMessage:
    """Сообщение стороны сделки. Коммитит вызывающий."""
    role = role_of(deal, sender)
    if role is None:
        raise ChatError("Сделка не найдена")
    if not is_open(deal):
        raise ChatError("Сделка завершена. Писать больше нельзя, история сохранена.")

    text = (text or "").strip() or None
    if text is None and media_path is None:
        raise ChatError("Пустое сообщение")
    if text is not None and len(text) > MAX_TEXT:
        raise ChatError(f"Сообщение длиннее {MAX_TEXT} символов")

    await _assert_not_flooding(db, sender)

    now = utcnow()
    message = DealMessage(
        id=uuid.uuid4(),
        deal_id=deal.id,
        direction=OWN_DIRECTION[role],
        sender_id=sender.id,
        text=text,
        media_type="photo" if media_path else None,
        media_path=media_path,
        created_at=now,
    )
    db.add(message)

    deal.last_message_at = now
    # Своё сообщение прочитано: иначе оно считалось бы непрочитанным у автора
    _mark_seen(deal, role, now)

    # Первое сообщение переводит сделку в «идёт переписка»
    if deal.status == DealStatus.PAID_ESCROW:
        deal.status = DealStatus.CHAT_OPENED
    return message


async def post_system(
    db: AsyncSession,
    deal: Deal,
    kind: str,
    text: str,
    *,
    actor: User | None = None,
) -> DealMessage:
    """
    Сообщение площадки в переписку: оплата, отправка, спор, завершение.

    actor — тот, чьё действие вызвало сообщение. Ему оно не показывается
    непрочитанным: продавец, нажавший «Я отправил товар», и так это знает.
    """
    now = utcnow()
    message = DealMessage(
        id=uuid.uuid4(),
        deal_id=deal.id,
        direction=MessageDirection.SYSTEM,
        sender_id=None,
        kind=kind,
        text=text,
        created_at=now,
    )
    db.add(message)
    deal.last_message_at = now

    role = role_of(deal, actor) if actor is not None else None
    if role is not None:
        _mark_seen(deal, role, now)
    return message


async def post_moderator(db: AsyncSession, deal: Deal, admin: User, text: str) -> DealMessage:
    """Модератор пишет в переписку сделки — обе стороны видят это сообщение."""
    text = (text or "").strip()
    if not text:
        raise ChatError("Пустое сообщение")
    if len(text) > MAX_TEXT:
        raise ChatError(f"Сообщение длиннее {MAX_TEXT} символов")

    now = utcnow()
    message = DealMessage(
        id=uuid.uuid4(),
        deal_id=deal.id,
        direction=MessageDirection.MODERATOR,
        sender_id=admin.id,
        text=text,
        created_at=now,
    )
    db.add(message)
    deal.last_message_at = now
    return message


def mark_read(deal: Deal, user: User) -> datetime:
    """Сторона прочитала переписку до текущего момента. Коммитит вызывающий."""
    role = role_of(deal, user)
    if role is None:
        raise ChatError("Сделка не найдена")
    now = utcnow()
    _mark_seen(deal, role, now)
    return read_at(deal, role)


def close_chat(deal: Deal) -> None:
    """Закрывает переписку на запись. История остаётся читаемой."""
    deal.chat_closed = True


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

async def unread_counts(db: AsyncSession, user: User) -> dict[uuid.UUID, int]:
    """
    Непрочитанное по сделкам пользователя.

    Два запроса вместо одного с CASE: у покупателя и продавца разные колонки
    прочтения и разное «своё» направление, и так читается проще.
    """
    counts: dict[uuid.UUID, int] = {}
    for role, party, seen in (
        ("buyer", Deal.buyer_id, Deal.buyer_read_at),
        ("seller", Deal.seller_id, Deal.seller_read_at),
    ):
        rows = (
            await db.execute(
                select(DealMessage.deal_id, func.count())
                .join(Deal, Deal.id == DealMessage.deal_id)
                .where(
                    party == user.id,
                    DealMessage.direction != OWN_DIRECTION[role],
                    or_(seen.is_(None), DealMessage.created_at > seen),
                )
                .group_by(DealMessage.deal_id)
            )
        ).all()
        for deal_id, count in rows:
            counts[deal_id] = counts.get(deal_id, 0) + count
    return counts


async def _latest_messages(
    db: AsyncSession, deal_ids: list[uuid.UUID]
) -> dict[uuid.UUID, DealMessage]:
    if not deal_ids:
        return {}
    rows = (
        await db.execute(
            select(DealMessage)
            .where(DealMessage.deal_id.in_(deal_ids))
            .order_by(DealMessage.deal_id, DealMessage.created_at.desc())
            .distinct(DealMessage.deal_id)
        )
    ).scalars().all()
    return {m.deal_id: m for m in rows}


async def _context(
    db: AsyncSession, deals: list[Deal]
) -> tuple[dict[uuid.UUID, SellerProfile], dict[uuid.UUID, str | None]]:
    """Магазины продавцов и фото товаров — пачкой на весь список."""
    seller_ids = {d.seller_id for d in deals}
    stores = {
        p.user_id: p
        for p in (
            await db.execute(select(SellerProfile).where(SellerProfile.user_id.in_(seller_ids)))
        ).scalars().all()
    } if seller_ids else {}

    item_ids = {d.order_item_id for d in deals if d.order_item_id}
    images: dict[uuid.UUID, str | None] = {}
    if item_ids:
        for item in (
            await db.execute(select(OrderItem).where(OrderItem.id.in_(item_ids)))
        ).scalars().all():
            snapshot = item.product_snapshot or {}
            gallery = snapshot.get("images") or []
            images[item.id] = gallery[0] if gallery else snapshot.get("image_url")
    return stores, images


def _author_for(message: DealMessage, viewer_role: str | None) -> str:
    author = AUTHOR[message.direction]
    if viewer_role is None or author in ("system", "moderator"):
        return author
    return "me" if author == viewer_role else "them"


def message_dto(message: DealMessage, viewer_role: str, counterpart_seen: datetime | None) -> dict:
    author = _author_for(message, viewer_role)
    state = None
    if author == "me":
        state = (
            "read"
            if counterpart_seen is not None and counterpart_seen >= message.created_at
            else "sent"
        )
    return {
        "id": str(message.id),
        "from": author,
        "kind": message.kind,
        "text": message.text,
        "photo_url": deal_media.signed_url(message.media_path) if message.media_path else None,
        # Вложение, пришедшее когда-то через бота: файла у нас нет, есть
        # только file_id Telegram — показываем пометку, а не пустой пузырь
        "legacy_media": (
            message.media_type if message.media_type and not message.media_path else None
        ),
        "created_at": iso(message.created_at),
        "state": state,
    }


def admin_message_dto(message: DealMessage) -> dict:
    return {
        "id": str(message.id),
        "from": AUTHOR[message.direction],
        "kind": message.kind,
        "text": message.text,
        "photo_url": deal_media.signed_url(message.media_path) if message.media_path else None,
        "media_type": message.media_type,
        # file_id позволяет админу переслать себе вложение, пришедшее через бота
        "media_file_id": message.media_file_id,
        "delivery_error": message.delivery_error,
        "created_at": iso(message.created_at),
    }


def _last_dto(message: DealMessage | None, role: str) -> dict | None:
    if message is None:
        return None
    return {
        "from": _author_for(message, role),
        "text": message.text,
        "photo": bool(message.media_path or message.media_type),
        "created_at": iso(message.created_at),
    }


def deal_dto(
    deal: Deal,
    role: str,
    *,
    store: SellerProfile | None,
    image: str | None,
    unread: int = 0,
    last: DealMessage | None = None,
    reviewed: bool = False,
) -> dict:
    return {
        "id": str(deal.id),
        "number": deal.number,
        "product_name": deal.product_name,
        # order_id и product_id нужны форме отзыва: эндпоинт отзывов опознаёт
        # покупку по заказу и товару
        "order_id": str(deal.order_id),
        "product_id": str(deal.product_id) if deal.product_id else None,
        "product_image": image,
        "role": role,
        "status": deal.status.value,
        "amount_ton": str(from_minor(deal.amount_nano, "TON")),
        "seller_amount_ton": str(from_minor(deal.seller_amount_nano, "TON")),
        "commission_ton": str(from_minor(deal.commission_nano, "TON")),
        "paid_at": iso(deal.created_at),
        "delivered_at": iso(deal.delivered_claimed_at),
        "confirm_deadline_at": iso(deal.confirm_deadline_at),
        "confirmed_at": iso(deal.confirmed_at),
        "released_at": iso(deal.released_at),
        "refunded_at": iso(deal.refunded_at),
        "dispute_reason": deal.dispute_reason,
        "chat_closed": deal.chat_closed,
        "chat_open": is_open(deal),
        "reviewed": reviewed,
        # Покупатель видит магазин; продавцу имя покупателя не отдаём вовсе
        "store": (
            {
                "name": store.display_name,
                "verified": store.is_verified,
                "avatar_url": store.avatar_url,
            }
            if store is not None and role == "buyer" else None
        ),
        "unread": unread,
        "last_message": _last_dto(last, role),
        "last_activity_at": iso(deal.last_message_at or deal.created_at),
        "counterpart_read_at": iso(read_at(deal, other(role))),
        "created_at": iso(deal.created_at),
    }


async def deal_dtos(
    db: AsyncSession, deals: list[Deal], user: User, *, reviewed: set[uuid.UUID] = frozenset()
) -> list[dict]:
    stores, images = await _context(db, deals)
    unread = await unread_counts(db, user)
    latest = await _latest_messages(db, [d.id for d in deals])
    return [
        deal_dto(
            d, role_of(d, user),
            store=stores.get(d.seller_id),
            image=images.get(d.order_item_id),
            unread=unread.get(d.id, 0),
            last=latest.get(d.id),
            reviewed=d.id in reviewed,
        )
        for d in deals
    ]


async def _dto_for_role(db: AsyncSession, deal: Deal, role: str) -> dict:
    stores, images = await _context(db, [deal])
    latest = await _latest_messages(db, [deal.id])
    viewer = await db.get(User, party_id(deal, role))
    unread = (await unread_counts(db, viewer)).get(deal.id, 0) if viewer else 0
    return deal_dto(
        deal, role,
        store=stores.get(deal.seller_id),
        image=images.get(deal.order_item_id),
        unread=unread,
        last=latest.get(deal.id),
    )


# ---------------------------------------------------------------------------
# Живые обновления
# ---------------------------------------------------------------------------
#
# Вызываются после коммита: событие о строке, которую потом откатили,
# показало бы сообщение, которого нет.

async def push_message(deal: Deal, message: DealMessage) -> None:
    for role in ("buyer", "seller"):
        await manager.send_personal_message(
            {
                "type": "deal_message",
                "deal_id": str(deal.id),
                "message": message_dto(message, role, read_at(deal, other(role))),
            },
            str(party_id(deal, role)),
        )


async def push_read(deal: Deal, reader_role: str) -> None:
    """Собеседнику — что его сообщения прочитаны: галочки становятся двойными."""
    await manager.send_personal_message(
        {
            "type": "deal_read",
            "deal_id": str(deal.id),
            "read_at": iso(read_at(deal, reader_role)),
        },
        str(party_id(deal, other(reader_role))),
    )


async def push_deal(db: AsyncSession, deal: Deal) -> None:
    """Обеим сторонам — новое состояние сделки: статус, кнопки, срок."""
    for role in ("buyer", "seller"):
        await manager.send_personal_message(
            {"type": "deal_updated", "deal": await _dto_for_role(db, deal, role)},
            str(party_id(deal, role)),
        )


# Кто когда последний раз сообщал «печатает»: событие летит на каждое
# нажатие клавиши, а в базу за участниками сделки ходить на каждое незачем
_typing_seen: dict[tuple[str, str], float] = {}
TYPING_THROTTLE = 2.0


async def relay_typing(user_id: str, deal_id: str) -> None:
    """«Печатает…» у собеседника. Участие в сделке проверяется по базе."""
    key = (user_id, deal_id)
    now = time.monotonic()
    if now - _typing_seen.get(key, 0.0) < TYPING_THROTTLE:
        return
    if len(_typing_seen) > 10_000:
        _typing_seen.clear()
    _typing_seen[key] = now

    try:
        deal_uuid, user_uuid = uuid.UUID(deal_id), uuid.UUID(user_id)
    except (ValueError, TypeError):
        return

    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        deal = await db.get(Deal, deal_uuid)
    if deal is None or not is_open(deal):
        return

    if user_uuid == deal.buyer_id:
        target = deal.seller_id
    elif user_uuid == deal.seller_id:
        target = deal.buyer_id
    else:
        return
    await manager.send_personal_message(
        {"type": "deal_typing", "deal_id": deal_id}, str(target),
    )


# ---------------------------------------------------------------------------
# Уведомления ботом
# ---------------------------------------------------------------------------
#
# Бот больше не пересылает сообщения — он напоминает о непрочитанном:
#   * не сразу, а спустя NOTIFY_GRACE: если чат открыт, приложение за это
#     время отметит сообщение прочитанным, и бот промолчит;
#   * одно уведомление на пачку: пока сторона не прочитала, новые сообщения
#     новых уведомлений не дают. Исключение — если пачка тянется дольше
#     REMIND_AFTER: тогда напоминаем ещё раз.

NOTIFY_GRACE = timedelta(seconds=15)
REMIND_AFTER = timedelta(hours=6)
NOTIFY_LOOKBACK = timedelta(days=3)
PREVIEW_LIMIT = 110


def _preview(message: DealMessage) -> str:
    if message.media_path or message.media_type:
        text = "Фото" if not message.text else f"Фото · {message.text}"
    else:
        text = message.text or ""
    text = " ".join(text.replace("`", "").split())
    if len(text) > PREVIEW_LIMIT:
        text = text[: PREVIEW_LIMIT - 1].rstrip() + "…"
    return text


def chat_url(deal: Deal) -> str:
    return f"{settings.SITE_URL.rstrip('/')}/my/deals/{deal.id}"


def open_chat_keyboard(deal: Deal, label: str = "Открыть чат") -> dict | None:
    """
    Кнопка, открывающая переписку прямо в мини-аппе.

    Telegram принимает web_app только с https: на локальном стенде кнопку не
    добавляем, иначе он отклонит сообщение целиком.
    """
    url = chat_url(deal)
    if not url.startswith("https://"):
        return None
    return {"inline_keyboard": [[{"text": label, "web_app": {"url": url}}]]}


async def notify_unread(db: AsyncSession) -> int:
    from services.telegram_service import telegram_service

    now = utcnow()
    candidates = (
        await db.execute(
            select(Deal).where(
                Deal.last_message_at.isnot(None),
                Deal.last_message_at >= now - NOTIFY_LOOKBACK,
                or_(
                    Deal.buyer_read_at.is_(None),
                    Deal.last_message_at > Deal.buyer_read_at,
                    Deal.seller_read_at.is_(None),
                    Deal.last_message_at > Deal.seller_read_at,
                ),
            )
        )
    ).scalars().all()

    sent = 0
    for deal in candidates:
        for role in ("buyer", "seller"):
            seen = read_at(deal, role)
            conditions = [
                DealMessage.deal_id == deal.id,
                DealMessage.direction != OWN_DIRECTION[role],
            ]
            if seen is not None:
                conditions.append(DealMessage.created_at > seen)
            unread = (
                await db.execute(
                    select(DealMessage).where(*conditions).order_by(DealMessage.created_at)
                )
            ).scalars().all()
            if not unread:
                continue

            first, last = unread[0], unread[-1]
            if first.created_at > now - NOTIFY_GRACE:
                continue

            notified = getattr(deal, f"{role}_notified_at")
            if notified is not None and notified >= first.created_at:
                if last.created_at <= notified + REMIND_AFTER:
                    continue

            recipient = await db.get(User, party_id(deal, role))
            if recipient is None:
                continue

            author = AUTHOR[last.direction]
            if author == "system":
                who = "Площадка"
            elif author == "moderator":
                who = "Модератор"
            elif author == "seller":
                store = (
                    await db.execute(
                        select(SellerProfile).where(SellerProfile.user_id == deal.seller_id)
                    )
                ).scalars().first()
                who = store.display_name if store else "Продавец"
            else:
                who = "Покупатель"

            title = (
                f"Новое сообщение по сделке №{deal.number}"
                if len(unread) == 1
                else f"Новые сообщения по сделке №{deal.number} ({len(unread)})"
            )
            text = f"{title}\n{who}: {_preview(last)}"

            try:
                await telegram_service.send_message(
                    recipient.telegram_id, text,
                    parse_mode=None, reply_markup=open_chat_keyboard(deal),
                )
                sent += 1
            except Exception as e:
                # Отметку ставим и при ошибке: заблокировавшему бота иначе
                # стучались бы каждые двадцать секунд
                logger.warning("[CHAT] Уведомление по сделке #%s не доставлено: %s",
                               deal.number, e)
            setattr(deal, f"{role}_notified_at", now)

    await db.commit()
    return sent


# ---------------------------------------------------------------------------
# Тексты системных сообщений
# ---------------------------------------------------------------------------

def pay_text(deal: Deal) -> str:
    return (
        f"Оплата получена: {format_amount(deal.amount_nano, 'TON')}. "
        "Деньги удерживаются площадкой до подтверждения получения."
    )


def ship_text(deal: Deal) -> str:
    deadline = (
        f" Если не подтвердить, сделка закроется автоматически {ru_date(deal.confirm_deadline_at)}."
        if deal.confirm_deadline_at else ""
    )
    return (
        "Продавец отметил отправку. Подтвердите получение, и деньги уйдут продавцу."
        + deadline
    )


DONE_TEXT = "Покупатель подтвердил получение. Сделка завершена, чат закрыт."
AUTO_DONE_TEXT = (
    "Срок подтверждения истёк — сделка закрыта автоматически, "
    "деньги переведены продавцу. Чат закрыт."
)


def dispute_text(opener_role: str, reason: str) -> str:
    who = "Покупатель" if opener_role == "buyer" else "Продавец"
    return (
        f"{who} открыл спор: «{reason}».\n"
        "Деньги остаются у площадки до решения модератора. "
        "Переписка здесь будет учтена при разборе."
    )
