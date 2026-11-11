"""Retention and bot post lifecycle. Publication is opt-in per giveaway."""
from datetime import datetime, timedelta
from urllib.parse import urlparse
import re
from sqlalchemy import select, delete, func, or_, and_
from config import settings
from database import AsyncSessionLocal
from models.giveaway import Giveaway, GiveawayEntry, GiveawayChat, GiveawayDrawAttempt, GiveawayPostCleanup
from services.telegram_service import _call, TelegramApiError
from services import nft_preview

RETENTION = timedelta(days=30)


def retained_condition():
    return and_(Giveaway.status != "cancelled", or_(Giveaway.status != "finished",
        func.coalesce(Giveaway.finished_at, Giveaway.end_at) > datetime.utcnow() - RETENTION))


def expired(row):
    return row.status == "cancelled" or (row.status == "finished"
        and (row.finished_at or row.end_at) <= datetime.utcnow() - RETENTION)


async def remove_record(db, row):
    if row.post_chat_id and row.post_message_id:
        db.add(GiveawayPostCleanup(chat_id=row.post_chat_id, message_id=row.post_message_id,
                                  has_photo=int(bool(row.photo_url))))
    for model in (GiveawayDrawAttempt, GiveawayEntry, GiveawayChat):
        await db.execute(delete(model).where(model.giveaway_id == row.id))
    await db.delete(row)


async def purge(session_factory=AsyncSessionLocal):
    async with session_factory() as db:
        rows = (await db.scalars(select(Giveaway).where(or_(Giveaway.status == "cancelled",
            and_(Giveaway.status == "finished", func.coalesce(Giveaway.finished_at, Giveaway.end_at)
                 <= datetime.utcnow() - RETENTION)))
            .order_by(Giveaway.id).limit(30).with_for_update(skip_locked=True))).all()
        for row in rows:
            await remove_record(db, row)
        await db.commit()


async def check_post_target(chat_id):
    me = await _call("getMe", {})
    rights = await _call("getChatMember", {"chat_id": chat_id, "user_id": me["id"]})
    if rights.get("status") not in ("administrator", "creator") or rights.get("can_post_messages") is False:
        raise ValueError("Боту нужны права администратора и публикации в канале постов")


def participation_link(identifier):
    bot = settings.VITE_BOT_USERNAME.lstrip("@").strip()
    if not re.fullmatch(r"[a-zA-Z0-9_]{5,32}", bot):
        raise ValueError("Не настроено имя бота для ссылки на розыгрыш")
    return f"https://t.me/{bot}?startapp=giveaway_{identifier.hex}"


async def dispatch_post(session_factory=AsyncSessionLocal):
    # Mark before sending: a crashed/ambiguous send is never retried automatically.
    async with session_factory() as db:
        stale = (await db.scalars(select(Giveaway).where(Giveaway.post_status == "sending",
            Giveaway.post_started_at < datetime.utcnow() - timedelta(minutes=2))
            .with_for_update(skip_locked=True))).all()
        for row in stale:
            row.post_status = "unknown"
        row = await db.scalar(select(Giveaway).where(Giveaway.post_status == "queued",
            Giveaway.status.in_(("open", "scheduled")), Giveaway.end_at > datetime.utcnow())
            .order_by(Giveaway.created_at).limit(1).with_for_update(skip_locked=True))
        if not row:
            await db.commit()
            return False
        identifier = row.id
        row.post_status, row.post_started_at = "sending", datetime.utcnow()
        await db.commit()
    # Cancellation locks this same row and waits until the message ID is recorded.
    async with session_factory() as db:
        row = await db.scalar(select(Giveaway).where(Giveaway.id == identifier).with_for_update())
        if not row or row.post_status != "sending":
            return False
        try:
            try:
                nft_link = nft_preview.gift_url(row.prize)
            except ValueError:
                nft_link = None
            if not nft_link:
                row.photo_url = await nft_preview.ensure_photo(row.prize, row.photo_url)
            link = participation_link(row.id)
            prize = nft_link or row.prize[:250]
            caption = f"Giveaway\n\n{prize}\nОкончание: {row.end_at.strftime('%d.%m.%Y %H:%M')} UTC\nУчастие бесплатное."
            heading = [{"type": "bold", "offset": 0, "length": len("Giveaway")}]
            if nft_link:
                heading.append({"type": "url", "offset": len("Giveaway\n\n"), "length": len(prize)})
            payload = {"chat_id": row.post_chat_id, "reply_markup": {"inline_keyboard": [[{"text": "Участвовать", "url": link}]]}}
            use_photo = bool(row.photo_url) and not nft_link
            if use_photo:
                site = settings.SITE_URL.rstrip("/")
                if urlparse(site).scheme != "https":
                    raise ValueError("Для фото поста нужен HTTPS SITE_URL")
                payload.update(photo=site + row.photo_url, caption=caption, caption_entities=heading,
                               show_caption_above_media=True)
            else:
                payload["text"] = caption
                payload["entities"] = heading
                if nft_link:
                    # Telegram renders the collectible's own card; the Mini App
                    # keeps its separately stored high-resolution photo.
                    payload["link_preview_options"] = {"is_disabled": False, "url": nft_link,
                        "prefer_large_media": True, "show_above_text": False}
            result = await _call("sendPhoto" if use_photo else "sendMessage", payload)
            row.post_message_id, row.post_status = result["message_id"], "sent"
        except ValueError:
            row.post_status = "failed"
        except TelegramApiError as exc:
            row.post_status = "failed" if exc.error_code in (400, 401, 403, 404, 429) else "unknown"
        except Exception:
            row.post_status = "unknown"
        await db.commit()
    return True


async def erase_posts(session_factory=AsyncSessionLocal):
    async with session_factory() as db:
        jobs = (await db.scalars(select(GiveawayPostCleanup)
            .where(GiveawayPostCleanup.next_attempt_at <= datetime.utcnow())
            .order_by(GiveawayPostCleanup.next_attempt_at).limit(5)
            .with_for_update(skip_locked=True))).all()
        for job in jobs:
            payload = {"chat_id": job.chat_id, "message_id": job.message_id}
            try:
                try:
                    await _call("deleteMessage", payload)
                except TelegramApiError as exc:
                    text = exc.description.lower()
                    if "message to delete not found" not in text:
                        if "can't be deleted" not in text and "cannot be deleted" not in text:
                            raise
                        empty = "Розыгрыш недоступен."
                        try:
                            # NFT posts are now text with a native preview, even
                            # though the giveaway still has a photo for the app.
                            await _call("editMessageText", {**payload, "text": empty,
                                "link_preview_options": {"is_disabled": True},
                                "reply_markup": {"inline_keyboard": []}})
                        except TelegramApiError as edit_error:
                            description = edit_error.description.lower()
                            if not job.has_photo or edit_error.error_code != 400 or not (
                                "no text" in description or "not a text message" in description
                            ):
                                raise
                            await _call("editMessageMedia", {**payload, "media": {"type": "photo",
                                "media": settings.SITE_URL.rstrip('/') + "/uploads/products/placeholder.png",
                                "caption": empty}, "reply_markup": {"inline_keyboard": []}})
                await db.delete(job)
            except Exception:
                job.attempts += 1
                job.next_attempt_at = datetime.utcnow() + timedelta(minutes=min(60, 2 ** min(job.attempts, 6)))
        await db.commit()
