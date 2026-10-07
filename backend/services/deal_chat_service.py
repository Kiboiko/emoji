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
from services import deal_media, settings_service
from services.money import format_ton_short, from_minor
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
_MONTHS_EN = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

# Текст системного сообщения на двух языках: (русский, английский)
Texts = tuple[str, str]
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


def en_date(value: datetime) -> str:
    local = value + _TEXT_TZ
    return f"{_MONTHS_EN[local.month - 1]} {local.day}"


def language_of(user: User | None) -> str:
    """Язык, выбранный в приложении; кто не выбирал — русский, как и приложение."""
    return "en" if user is not None and user.app_language == "en" else "ru"


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
    text: Texts | str,
    *,
    actor: User | None = None,
) -> DealMessage:
    """
    Сообщение площадки в переписку: оплата, отправка, спор, завершение.

    text — пара (русский, английский): каждая сторона читает на языке,
    выбранном в приложении. actor — тот, чьё действие вызвало сообщение. Ему
    оно не показывается непрочитанным: продавец, нажавший «Я отправил
    товар», и так это знает.
    """
    ru, en = (text, None) if isinstance(text, str) else text
    now = utcnow()
    message = DealMessage(
        id=uuid.uuid4(),
        deal_id=deal.id,
        direction=MessageDirection.SYSTEM,
        sender_id=None,
        kind=kind,
        text=ru,
        text_en=en,
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
    """
    Закрывает переписку на запись. Ещё chat_retention_days дней история
    читается, потом пропадает у сторон.
    """
    deal.chat_closed = True
    if deal.chat_closed_at is None:
        deal.chat_closed_at = utcnow()


# ---------------------------------------------------------------------------
# Сколько живёт закрытая переписка
# ---------------------------------------------------------------------------
#
# После завершения сделки писать уже нельзя, но несколько дней переписку можно
# перечитать: забрать ключ или логин, свериться с договорённостями. Потом она
# пропадает у сторон. Из базы не удаляется: модератору переписка нужна и
# позже — при жалобе или проверке мошенничества.

async def retention_days(db: AsyncSession) -> int:
    return await settings_service.get_int(db, "chat_retention_days")


def chat_expires_at(deal: Deal, days: int) -> datetime | None:
    if not deal.chat_closed:
        return None
    closed = (
        deal.chat_closed_at or deal.released_at or deal.refunded_at
        or deal.last_message_at or deal.created_at
    )
    return closed + timedelta(days=days) if closed else None


def chat_expired(deal: Deal, days: int) -> bool:
    expires = chat_expires_at(deal, days)
    return expires is not None and expires <= utcnow()


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

async def unread_counts(db: AsyncSession, user: User) -> dict[uuid.UUID, int]:
    """
    Непрочитанное по сделкам пользователя.

    Два запроса вместо одного с CASE: у покупателя и продавца разные колонки
    прочтения и разное «своё» направление, и так читается проще.

    Переписка, которая уже пропала у сторон, не считается: иначе значок
    горел бы вечно, а открыть и прочитать её было бы негде.
    """
    visible_since = utcnow() - timedelta(days=await retention_days(db))
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
                    or_(Deal.chat_closed_at.is_(None), Deal.chat_closed_at > visible_since),
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
        # Английский вариант есть только у сообщений площадки; приложение
        # выбирает по своему языку и при отсутствии берёт text
        "text_en": message.text_en,
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
        "text_en": message.text_en,
        "photo": bool(message.media_path or message.media_type),
        "created_at": iso(message.created_at),
    }


def _presence(deal: Deal, counterpart: User | None) -> tuple[bool | None, str | None]:
    """
    В сети ли собеседник, а если нет — когда был.

    Только пока переписка открыта: писать в закрытую сделку нельзя, и
    следить, когда бывший покупатель заходит в приложение, продавцу незачем.
    """
    if counterpart is None or not is_open(deal):
        return None, None
    if manager.is_online(str(counterpart.id)):
        return True, None
    return False, iso(counterpart.last_seen_at)


def deal_dto(
    deal: Deal,
    role: str,
    *,
    store: SellerProfile | None,
    image: str | None,
    unread: int = 0,
    last: DealMessage | None = None,
    reviewed: bool = False,
    counterpart: User | None = None,
    retention: int = 7,
) -> dict:
    online, last_seen = _presence(deal, counterpart)
    expired = chat_expired(deal, retention)
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
        # До какого момента закрытую переписку ещё можно прочитать; после —
        # chat_expired, и сообщения сторонам больше не отдаются
        "chat_expires_at": iso(chat_expires_at(deal, retention)),
        "chat_expired": expired,
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
        "unread": 0 if expired else unread,
        "last_message": None if expired else _last_dto(last, role),
        "last_activity_at": iso(deal.last_message_at or deal.created_at),
        "counterpart_read_at": iso(read_at(deal, other(role))),
        "counterpart_online": online,
        "counterpart_last_seen_at": last_seen,
        "created_at": iso(deal.created_at),
    }


def _counterpart_id(deal: Deal, user: User) -> uuid.UUID:
    return deal.seller_id if user.id == deal.buyer_id else deal.buyer_id


async def deal_dtos(
    db: AsyncSession, deals: list[Deal], user: User, *, reviewed: set[uuid.UUID] = frozenset()
) -> list[dict]:
    stores, images = await _context(db, deals)
    unread = await unread_counts(db, user)
    latest = await _latest_messages(db, [d.id for d in deals])
    retention = await retention_days(db)
    other_ids = {_counterpart_id(d, user) for d in deals if is_open(d)}
    others = {
        u.id: u
        for u in (await db.execute(select(User).where(User.id.in_(other_ids)))).scalars().all()
    } if other_ids else {}
    return [
        deal_dto(
            d, role_of(d, user),
            store=stores.get(d.seller_id),
            image=images.get(d.order_item_id),
            unread=unread.get(d.id, 0),
            last=latest.get(d.id),
            reviewed=d.id in reviewed,
            counterpart=others.get(_counterpart_id(d, user)),
            retention=retention,
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
        counterpart=await db.get(User, party_id(deal, other(role))),
        retention=await retention_days(db),
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


async def presence_changed(user_id: str, was_online: bool, db: AsyncSession | None = None) -> None:
    """
    Человек открыл или свернул приложение — собеседникам по открытым сделкам.

    Вызывается после каждого изменения соединений пользователя; если «в сети»
    от этого не поменялось (второе устройство, повторный сигнал), молчит.
    Время пишется и при входе, и при выходе: если сервер перезапустится, не
    успев записать выход, «был(а) в сети» покажет хотя бы время входа.
    """
    online = manager.is_online(user_id)
    if online == was_online:
        return
    try:
        user_uuid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        return

    now = utcnow()
    if db is None:
        from database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            deals = await _touch_last_seen(session, user_uuid, now)
    else:
        deals = await _touch_last_seen(db, user_uuid, now)

    for deal in deals:
        target = deal.seller_id if deal.buyer_id == user_uuid else deal.buyer_id
        await manager.send_personal_message(
            {
                "type": "deal_presence",
                "deal_id": str(deal.id),
                "online": online,
                "last_seen_at": None if online else iso(now),
            },
            str(target),
        )


async def _touch_last_seen(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> list[Deal]:
    user = await db.get(User, user_id)
    if user is None:
        return []
    user.last_seen_at = now
    deals = await open_deals_for(db, user)
    await db.commit()
    return list(deals)


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


def _preview(message: DealMessage, language: str = "ru") -> str:
    body = message.text_en if language == "en" and message.text_en else message.text
    photo = "Photo" if language == "en" else "Фото"
    if message.media_path or message.media_type:
        text = photo if not body else f"{photo} · {body}"
    else:
        text = body or ""
    text = " ".join(text.replace("`", "").split())
    if len(text) > PREVIEW_LIMIT:
        text = text[: PREVIEW_LIMIT - 1].rstrip() + "…"
    return text


def chat_url(deal: Deal) -> str:
    return f"{settings.SITE_URL.rstrip('/')}/my/deals/{deal.id}"


def open_chat_label(language: str) -> str:
    return "Open chat" if language == "en" else "Открыть чат"


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
            en = language_of(recipient) == "en"

            author = AUTHOR[last.direction]
            if author == "system":
                who = "Marketplace" if en else "Площадка"
            elif author == "moderator":
                who = "Moderator" if en else "Модератор"
            elif author == "seller":
                store = (
                    await db.execute(
                        select(SellerProfile).where(SellerProfile.user_id == deal.seller_id)
                    )
                ).scalars().first()
                who = store.display_name if store else ("Seller" if en else "Продавец")
            else:
                who = "Buyer" if en else "Покупатель"

            if en:
                title = (
                    f"New message in deal #{deal.number}"
                    if len(unread) == 1
                    else f"New messages in deal #{deal.number} ({len(unread)})"
                )
            else:
                title = (
                    f"Новое сообщение по сделке №{deal.number}"
                    if len(unread) == 1
                    else f"Новые сообщения по сделке №{deal.number} ({len(unread)})"
                )
            text = f"{title}\n{who}: {_preview(last, 'en' if en else 'ru')}"

            try:
                await telegram_service.send_message(
                    recipient.telegram_id, text,
                    parse_mode=None,
                    reply_markup=open_chat_keyboard(deal, open_chat_label("en" if en else "ru")),
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

#
# Каждый текст — пара (русский, английский). Английский пишется сразу, а не
# переводится при показе: в нём те же суммы и даты, что были на момент
# события, даже если сделка потом изменится.

def pay_text(deal: Deal) -> Texts:
    amount = format_ton_short(deal.amount_nano)
    return (
        f"Оплата получена: {amount}. "
        "Деньги удерживаются площадкой до подтверждения получения.",
        f"Payment received: {amount}. "
        "The marketplace holds the money until receipt is confirmed.",
    )


def ship_text(deal: Deal) -> Texts:
    deadline = deal.confirm_deadline_at
    return (
        "Продавец отметил отправку. Подтвердите получение, и деньги уйдут продавцу."
        + (f" Если не подтвердить, сделка закроется автоматически {ru_date(deadline)}."
           if deadline else ""),
        "The seller marked the item as sent. Confirm receipt and the money goes to the seller."
        + (f" If you do not confirm, the deal closes automatically on {en_date(deadline)}."
           if deadline else ""),
    )


DONE_TEXT: Texts = (
    "Покупатель подтвердил получение. Сделка завершена, чат закрыт.",
    "The buyer confirmed receipt. The deal is complete, the chat is closed.",
)
AUTO_DONE_TEXT: Texts = (
    "Срок подтверждения истёк — сделка закрыта автоматически, "
    "деньги переведены продавцу. Чат закрыт.",
    "The confirmation period has expired — the deal closed automatically "
    "and the money went to the seller. The chat is closed.",
)


def refund_text(deal: Deal) -> Texts:
    amount = format_ton_short(deal.amount_nano)
    return (
        f"Продавец оформил возврат: {amount} вернулись на баланс покупателя. "
        "Сделка закрыта.",
        f"The seller issued a refund: {amount} went back to the buyer's balance. "
        "The deal is closed.",
    )


def dispute_text(opener_role: str, reason: str) -> Texts:
    buyer = opener_role == "buyer"
    return (
        f"{'Покупатель' if buyer else 'Продавец'} открыл спор: «{reason}».\n"
        "Деньги остаются у площадки до решения модератора. "
        "Переписка здесь будет учтена при разборе.",
        f"The {'buyer' if buyer else 'seller'} opened a dispute: “{reason}”.\n"
        "The money stays with the marketplace until a moderator decides. "
        "This conversation will be taken into account.",
    )


def resolved_text(release: bool, comment: str | None) -> Texts:
    if release:
        ru = "Спор решён в пользу продавца, деньги перечислены ему."
        en = "The dispute was resolved in the seller's favour, the money went to the seller."
    else:
        ru = "Спор решён в пользу покупателя, средства возвращены на его баланс."
        en = "The dispute was resolved in the buyer's favour, the money went back to the buyer's balance."
    # Комментарий модератора не переводим — он один на оба языка
    note = (comment or "").strip()
    return (f"{ru}\n{note}".strip(), f"{en}\n{note}".strip())
