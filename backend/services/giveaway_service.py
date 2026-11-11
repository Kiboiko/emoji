"""Entry verification and resumable selection; no NFT transfers or client-picked winners."""
from datetime import datetime, timedelta
import hashlib
import asyncio
import secrets
import uuid
from sqlalchemy import select, func, or_
from database import AsyncSessionLocal
from models.giveaway import Giveaway, GiveawayChat, GiveawayEntry, GiveawayDrawAttempt
from models.user import User
from services.telegram_service import _call

DRAWABLE = ("scheduled", "open", "drawing", "waiting_for_telegram")


class GiveawayError(ValueError):
    pass


def member_allowed(member):
    return member.get("status") in ("member", "administrator", "creator") or (
        member.get("status") == "restricted" and member.get("is_member") is True)


async def chats(db, giveaway_id):
    return (await db.scalars(select(GiveawayChat).where(GiveawayChat.giveaway_id == giveaway_id).order_by(GiveawayChat.id))).all()


async def preflight(requirements):
    me = await _call("getMe", {})
    for chat in requirements:
        member = await _call("getChatMember", {"chat_id": chat.chat_id, "user_id": me["id"]})
        if member.get("status") not in ("administrator", "creator"):
            raise GiveawayError("Бот должен быть администратором всех обязательных чатов")


async def _membership(requirements, telegram_id):
    # Also check the bot's rights: loss of access must not exclude a candidate.
    await preflight(requirements)
    results = []
    for chat in requirements:
        result = await _call("getChatMember", {"chat_id": chat.chat_id, "user_id": telegram_id})
        if result.get("status") not in ("member", "administrator", "creator", "restricted", "left", "kicked"):
            raise GiveawayError("Неизвестный статус Telegram")
        results.append({"chat_id": str(chat.chat_id), "requirement_id": str(chat.id), "joined": member_allowed(result)})
    return results


_membership_slots = asyncio.Semaphore(2)


async def membership(requirements, telegram_id):
    try:
        await asyncio.wait_for(_membership_slots.acquire(), timeout=2)
    except TimeoutError:
        raise GiveawayError("Проверки заняты, повторите позже")
    try:
        return await _membership(requirements, telegram_id)
    finally:
        _membership_slots.release()


async def verify_entry(db, giveaway_id, user, join=False):
    now = datetime.utcnow()
    giveaway = await db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id).with_for_update())
    if giveaway is None or giveaway.status not in ("open", "scheduled") or not (giveaway.start_at <= now < giveaway.end_at):
        raise GiveawayError("Приём заявок закрыт")
    entry = await db.scalar(select(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway.id, GiveawayEntry.user_id == user.id))
    if entry and entry.status == "joined" and join:
        return {"joined": True, "checks": [], "entry_label": "Участник " + entry.id.hex[:8]}
    if entry and entry.checked_at and (now - entry.checked_at).total_seconds() < 10:
        raise GiveawayError("Повторите проверку через 10 секунд")
    if entry is None:
        entry = GiveawayEntry(giveaway_id=giveaway.id, user_id=user.id)
        db.add(entry)
    entry.checked_at = now
    await db.flush()
    entry_id, version, eligibility = entry.id, giveaway.version, entry.eligibility_version
    requirements = await chats(db, giveaway.id)
    await db.commit()
    try:
        results = await membership(requirements, user.telegram_id)
    except Exception:
        raise GiveawayError("Не удалось проверить подписки. Повторите позже; результат участия не изменён.")
    row = await db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id).with_for_update().execution_options(populate_existing=True))
    accepted_at = datetime.utcnow()
    if row is None or row.version != version or row.status not in ("scheduled", "open") or not (row.start_at <= accepted_at < row.end_at):
        raise GiveawayError("Приём заявок завершён во время проверки")
    active_user = await db.get(User, user.id, populate_existing=True)
    if active_user.is_blocked:
        raise GiveawayError("Участие недоступно")
    entry = await db.get(GiveawayEntry, entry_id, populate_existing=True)
    if entry is None or entry.eligibility_version != eligibility:
        raise GiveawayError("Подписка изменилась во время проверки. Повторите участие.")
    passed = bool(requirements) and len(results) == len(requirements) and all(result["joined"] for result in results)
    if join and passed:
        entry.status, entry.entered_at, entry.error_code = "joined", accepted_at, None
    elif not passed and entry.status == "joined":
        entry.status, entry.error_code = "excluded", "unsubscribed"
        entry.eligibility_version += 1
    await db.commit()
    joined = entry.status == "joined"
    return {"joined": joined, "checks": results, "entry_label": "Участник " + entry.id.hex[:8] if joined else None}


async def draw_one(giveaway_id, session_factory=AsyncSessionLocal):
    now, token = datetime.utcnow(), uuid.uuid4()
    async with session_factory() as db:
        row = await db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id).with_for_update())
        if not row or row.status not in DRAWABLE or row.end_at > now or (row.lease_until and row.lease_until > now):
            return False
        if row.draw_started_at is None:
            identifiers = (await db.scalars(select(GiveawayEntry.id).where(GiveawayEntry.giveaway_id == row.id,
                GiveawayEntry.status == "joined", GiveawayEntry.entered_at < row.end_at).order_by(GiveawayEntry.id))).all()
            row.draw_started_at, row.snapshot_count = now, len(identifiers)
            row.snapshot_hash = hashlib.sha256("\n".join(map(str, identifiers)).encode()).hexdigest()
        attempt = await db.scalar(select(GiveawayDrawAttempt).where(GiveawayDrawAttempt.giveaway_id == row.id,
            GiveawayDrawAttempt.status == "selected").order_by(GiveawayDrawAttempt.ordinal).limit(1))
        if attempt is None:
            candidates = select(GiveawayEntry).where(GiveawayEntry.giveaway_id == row.id,
                GiveawayEntry.status == "joined", GiveawayEntry.entered_at < row.end_at)
            count = await db.scalar(select(func.count()).select_from(candidates.subquery()))
            if not count:
                row.status, row.finished_at, row.lease_until = "finished", now, None
                await db.commit()
                return True
            entry = await db.scalar(candidates.order_by(GiveawayEntry.id).offset(secrets.randbelow(count)).limit(1))
            ordinal = (await db.scalar(select(func.count()).select_from(GiveawayDrawAttempt)
                .where(GiveawayDrawAttempt.giveaway_id == row.id))) + 1
            attempt = GiveawayDrawAttempt(giveaway_id=row.id, entry_id=entry.id, ordinal=ordinal)
            db.add(attempt)
            await db.flush()
        else:
            entry = await db.get(GiveawayEntry, attempt.entry_id)
        owner = await db.get(User, entry.user_id)
        requirements = await chats(db, row.id)
        attempt_id, entry_id = attempt.id, entry.id
        row.status, row.lease_token, row.lease_until = "drawing", token, now + timedelta(minutes=5)
        await db.commit()
    outcome = None
    if owner.is_blocked:
        outcome = False
    else:
        try:
            checks = await membership(requirements, owner.telegram_id)
            outcome = bool(checks) and all(c["joined"] for c in checks)
        except Exception:
            pass
    async with session_factory() as db:
        row = await db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id).with_for_update())
        if row is None or row.status != "drawing" or row.lease_token != token:
            return False
        attempt = await db.get(GiveawayDrawAttempt, attempt_id)
        entry = await db.get(GiveawayEntry, entry_id)
        owner = await db.get(User, entry.user_id)
        row.lease_token, row.lease_until = None, None
        if outcome is None:
            row.status, row.error_code = "waiting_for_telegram", "membership_unavailable"
            row.lease_until = datetime.utcnow() + timedelta(seconds=30)
        elif not outcome or owner.is_blocked or entry.status != "joined":
            attempt.status, entry.status, entry.error_code = "rejected", "excluded", "not_eligible_at_draw"
            row.status, row.error_code = "drawing", None
        else:
            attempt.status, entry.status = "eligible", "winner"
            row.status, row.winner_user_id, row.finished_at = "finished", entry.user_id, datetime.utcnow()
            row.public_winner_label = (owner.first_name or "Участник " + entry.id.hex[:8])[:60]
            row.public_winner_username, row.error_code = owner.username, None
        await db.commit()
    return True


async def due_giveaways(db):
    now = datetime.utcnow()
    return (await db.scalars(select(Giveaway.id).where(Giveaway.status.in_(DRAWABLE),
        Giveaway.end_at <= now, or_(Giveaway.lease_until.is_(None), Giveaway.lease_until <= now))
        .order_by(Giveaway.end_at, Giveaway.id).limit(10))).all()


async def membership_left(db, chat_id, telegram_id, occurred_at=None):
    """Called for every chat, including giveaway-only chats with no subscription channel."""
    now = datetime.utcnow()
    event_at = occurred_at or now
    rows = (await db.scalars(select(Giveaway).join(GiveawayChat, GiveawayChat.giveaway_id == Giveaway.id)
        .where(GiveawayChat.chat_id == chat_id, Giveaway.status.in_(DRAWABLE),
               Giveaway.start_at <= event_at, Giveaway.end_at > event_at)
        .order_by(Giveaway.id).with_for_update(of=Giveaway))).all()
    changed = 0
    for row in rows:
        entry = await db.scalar(select(GiveawayEntry).join(User, User.id == GiveawayEntry.user_id)
            .where(GiveawayEntry.giveaway_id == row.id, User.telegram_id == telegram_id))
        if entry and entry.status in ("joined", "checking"):
            # Ignore old updates from before the most recent successful admission.
            if entry.entered_at and event_at < entry.entered_at.replace(microsecond=0):
                continue
            entry.status, entry.error_code = "excluded", "unsubscribed"
            entry.eligibility_version += 1
            changed += 1
    return changed


async def recheck_entries(session_factory=AsyncSessionLocal):
    async with session_factory() as db:
        now = datetime.utcnow()
        rows = (await db.execute(select(GiveawayEntry.giveaway_id, GiveawayEntry.user_id)
            .join(Giveaway, Giveaway.id == GiveawayEntry.giveaway_id)
            .where(GiveawayEntry.status == "joined", Giveaway.status.in_(("open", "scheduled")),
                   Giveaway.end_at > now, or_(GiveawayEntry.checked_at.is_(None),
                   GiveawayEntry.checked_at < now - timedelta(minutes=5)))
            .order_by(GiveawayEntry.checked_at.asc().nulls_first(), GiveawayEntry.id).limit(3))).all()
    for giveaway_id, user_id in rows:
        async with session_factory() as db:
            user = await db.get(User, user_id)
            if user:
                try:
                    await verify_entry(db, giveaway_id, user)
                except GiveawayError:
                    await db.rollback()
