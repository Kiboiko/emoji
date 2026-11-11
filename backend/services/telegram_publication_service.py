"""Durable outbox. Ambiguous network outcomes are never retried automatically."""
from datetime import datetime, timedelta
from decimal import Decimal
from html import escape
from pathlib import Path
import uuid
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from config import settings
from database import AsyncSessionLocal
from models.telegram_publication import LargeDealConfig, TelegramPublication
from models.order import OrderItem
from models.p2p import DealStatus, SellerProfile
from services.telegram_service import _call, TelegramApiError


async def configuration(db):
    await db.execute(insert(LargeDealConfig).values(id=1, enabled=False, min_nano=0).on_conflict_do_nothing())
    return await db.get(LargeDealConfig, 1, populate_existing=True)


async def preflight(chat_id):
    me = await _call("getMe", {})
    chat = await _call("getChat", {"chat_id": chat_id})
    member = await _call("getChatMember", {"chat_id": chat_id, "user_id": me["id"]})
    if member.get("status") not in ("administrator", "creator"):
        raise ValueError("Бот должен быть администратором чата")
    if chat.get("type") == "channel" and member.get("status") != "creator" and not member.get("can_post_messages"):
        raise ValueError("Боту нужно право публикации в канале")
    return {"title": chat.get("title", ""), "type": chat.get("type")}


async def enqueue(db, deal):
    config = await configuration(db)
    if not config.enabled or not config.chat_id or config.min_nano <= 0 or deal.status != DealStatus.RELEASED:
        return
    if deal.amount_nano < config.min_nano or not config.enabled_at or deal.released_at < config.enabled_at:
        return
    item = await db.get(OrderItem, deal.order_item_id) if deal.order_item_id else None
    seller = await db.scalar(select(SellerProfile).where(SellerProfile.user_id == deal.seller_id))
    snapshot = item.product_snapshot if item else {}
    name = str(deal.product_name or "Товар")[:250]
    price = format((Decimal(deal.amount_nano) / Decimal(1_000_000_000)).normalize(), "f")
    if not price:
        price = "0"
    # Public projection only; no buyer identity or delivery instructions.
    payload = {"text": f"<b>Завершена крупная сделка</b>\n{escape(name)}\n"
               f"Магазин: {escape(seller.display_name if seller else 'Маркет')}\n<b>{price} Gram</b>",
               "photo": snapshot.get("image_url"), "product_id": str(deal.product_id) if deal.product_id else None}
    await db.execute(insert(TelegramPublication).values(id=uuid.uuid4(), kind="large_deal", source_id=deal.id,
        destination_chat_id=config.chat_id, thread_id=config.thread_id, payload=payload, status="pending", attempts=0,
        next_attempt_at=datetime.utcnow(), created_at=datetime.utcnow()).on_conflict_do_nothing())


def safe_photo(url):
    if not isinstance(url, str) or not url.startswith("/uploads/"):
        return None
    root = Path(settings.UPLOAD_DIR).resolve()
    path = (root / url.split("?", 1)[0].removeprefix("/uploads/")).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    # Telegram may fetch only this site's public uploads; arbitrary URLs are not used.
    return settings.SITE_URL.rstrip("/") + url.split("?", 1)[0]


async def send(publication):
    payload = {"chat_id": publication.destination_chat_id, "parse_mode": "HTML"}
    if publication.thread_id:
        payload["message_thread_id"] = publication.thread_id
    product_id = publication.payload.get("product_id")
    bot = settings.VITE_BOT_USERNAME.lstrip("@")
    if bot and product_id:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": "Открыть товар", "url":
            f"https://t.me/{bot}?startapp=product_{uuid.UUID(product_id).hex}"}]]}
    photo = safe_photo(publication.payload.get("photo"))
    if photo:
        try:
            return await _call("sendPhoto", {**payload, "photo": photo, "caption": publication.payload["text"]})
        except TelegramApiError as exc:
            if exc.error_code != 400:
                raise
    return await _call("sendMessage", {**payload, "text": publication.payload["text"]})


async def dispatch_one(session_factory=AsyncSessionLocal):
    now = datetime.utcnow()
    async with session_factory() as db:
        # A process may have died after Telegram accepted its request.
        await db.execute(update(TelegramPublication).where(TelegramPublication.status == "sending",
            TelegramPublication.lease_until < now).values(status="unknown", error_code="lease_expired"))
        publication = await db.scalar(select(TelegramPublication).where(
            TelegramPublication.status.in_(["pending", "retry"]), TelegramPublication.next_attempt_at <= now)
            .order_by(TelegramPublication.created_at).with_for_update(skip_locked=True).limit(1))
        if publication is None:
            await db.commit()
            return False
        config = await configuration(db)
        if not config.enabled or config.chat_id != publication.destination_chat_id or config.thread_id != publication.thread_id:
            publication.status = "suppressed"
            await db.commit()
            return True
        publication.status, publication.lease_until = "sending", now + timedelta(minutes=2)
        publication.attempts += 1
        await db.commit()
        ident = publication.id
    status, code, message_id, next_at = "sent", None, None, now
    try:
        result = await send(publication)
        message_id = result["message_id"]
    except TelegramApiError as exc:
        code = f"telegram_{exc.error_code or 'unknown'}"
        if exc.error_code == 429 and publication.attempts < 5:
            status, next_at = "retry", now + timedelta(seconds=max(1, exc.retry_after or 60))
        elif exc.error_code and 400 <= exc.error_code < 500:
            status = "failed"
        else:
            status = "unknown"
    except Exception:
        status, code = "unknown", "transport_or_response_unknown"
    async with session_factory() as db:
        row = await db.scalar(select(TelegramPublication).where(TelegramPublication.id == ident).with_for_update())
        if row.status == "sending":
            row.status, row.error_code, row.telegram_message_id = status, code, message_id
            row.next_attempt_at, row.lease_until = next_at, None
            if status == "sent":
                row.sent_at = datetime.utcnow()
        await db.commit()
    return True
