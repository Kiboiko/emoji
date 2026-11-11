"""Private conversations before purchase; never create unpaid escrow deals."""
from datetime import datetime, timedelta
import uuid
from sqlalchemy import select, func, delete, or_, and_, text, exists
from fastapi import HTTPException
from database import AsyncSessionLocal
from models.inquiry import Inquiry, InquiryMessage, InquiryMediaCleanup
from models.p2p import SellerProfile, SellerStatus, Deal, DealMessage, MessageDirection
from models.user import User
from services import deal_media
from services.deal_chat_service import retention_days

TTL = timedelta(hours=72)


async def own(db, identifier, user, lock=False):
    stmt = select(Inquiry).where(Inquiry.id == identifier, or_(Inquiry.buyer_id == user.id, Inquiry.seller_id == user.id))
    if lock: stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if not row or (not row.linked_deal_id and row.expires_at and row.expires_at <= datetime.utcnow()):
        raise HTTPException(404, "Переписка не найдена или удалена по сроку")
    return row


async def erase(db, row):
    db.add(InquiryMediaCleanup(inquiry_id=row.id))
    await db.execute(delete(InquiryMessage).where(InquiryMessage.inquiry_id == row.id))
    await db.delete(row)


async def resolve_store(db, store_id, user, kind="seller"):
    if kind == "channel":
        from models.subscription import Channel, ChannelStatus
        channel = await db.get(Channel, store_id)
        if not channel or channel.status != ChannelStatus.ACTIVE:
            raise HTTPException(404, "Магазин недоступен")
        seller = await db.scalar(select(SellerProfile).where(SellerProfile.user_id == channel.owner_user_id))
    else:
        seller = await db.get(SellerProfile, store_id)
    if not seller or seller.status != SellerStatus.ACTIVE:
        raise HTTPException(404, "Магазин недоступен")
    owner = await db.get(User, seller.user_id)
    if not owner or owner.is_blocked:
        raise HTTPException(404, "Магазин недоступен")
    if seller.user_id == user.id:
        raise HTTPException(409, "Нельзя написать самому себе")
    return seller


async def prepare(db, store_id, user, kind="seller"):
    """Read-only preparation; opening a composer does not create a conversation."""
    seller = await resolve_store(db, store_id, user, kind)
    row = await db.scalar(select(Inquiry).where(Inquiry.buyer_id == user.id,
        Inquiry.seller_id == seller.user_id, Inquiry.paid_order_id.is_(None),
        Inquiry.expires_at > datetime.utcnow(), exists(select(InquiryMessage.id).where(InquiryMessage.inquiry_id == Inquiry.id))))
    if row:
        return await metadata(db, row, user)
    owner = await db.get(User, seller.user_id)
    return {"id": None, "name": seller.display_name, "role": "buyer", "store_id": str(seller.id),
        "avatar_url": seller.avatar_url or owner.photo_url, "my_avatar_url": user.photo_url,
        "expires_at": None, "paid": False, "deal_id": None, "unread": 0,
        "last_text": None, "last_photo": False, "last_activity_at": datetime.utcnow().isoformat() + "Z"}


async def open_chat(db, store_id, user, kind="seller"):
    seller = await resolve_store(db, store_id, user, kind)
    # Serialize opens and message-rate checks for this buyer across processes.
    key = (user.id.int & ((1 << 63) - 1))
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    row = await db.scalar(select(Inquiry).where(Inquiry.buyer_id == user.id,
        Inquiry.seller_id == seller.user_id, Inquiry.paid_order_id.is_(None)).with_for_update())
    now = datetime.utcnow()
    if row and row.expires_at and row.expires_at <= now:
        await erase(db, row)
        await db.flush()
        row = None
    if row is None:
        count = await db.scalar(select(func.count()).select_from(Inquiry).where(
            Inquiry.buyer_id == user.id, Inquiry.created_at > now - timedelta(days=1)))
        if count >= 30: raise HTTPException(429, "Слишком много новых диалогов. Повторите позже.")
        row = Inquiry(buyer_id=user.id, seller_id=seller.user_id, seller_profile_id=seller.id,
                      expires_at=now + TTL, created_at=now)
        db.add(row)
        await db.flush()
    return row


async def metadata(db, row, user):
    seller = await db.get(SellerProfile, row.seller_profile_id)
    buyer_role = row.buyer_id == user.id
    seen = row.buyer_read_at if buyer_role else row.seller_read_at
    unread = await db.scalar(select(func.count()).select_from(InquiryMessage).where(
        InquiryMessage.inquiry_id == row.id, InquiryMessage.sender_id != user.id,
        InquiryMessage.created_at > (seen or datetime.min)))
    last = await db.scalar(select(InquiryMessage).where(InquiryMessage.inquiry_id == row.id)
        .order_by(InquiryMessage.created_at.desc(), InquiryMessage.id.desc()).limit(1))
    counterpart = await db.get(User, row.seller_id if buyer_role else row.buyer_id)
    return snapshot(row, user, seller, unread, last, counterpart)


def snapshot(row, user, seller, unread, last, counterpart):
    buyer_role = row.buyer_id == user.id
    return {"id": str(row.id), "name": seller.display_name if buyer_role and seller else "Покупатель",
        "role": "buyer" if buyer_role else "seller", "store_id": str(row.seller_profile_id),
        "avatar_url": (seller.avatar_url if buyer_role and seller else None) or (counterpart.photo_url if counterpart else None),
        "my_avatar_url": (seller.avatar_url if not buyer_role and seller else None) or user.photo_url,
        "expires_at": row.expires_at.isoformat() + "Z" if row.expires_at else None,
        "paid": bool(row.paid_order_id), "deal_id": str(row.linked_deal_id) if row.linked_deal_id else None,
        "unread": unread, "last_text": last.text if last else None, "last_photo": bool(last and last.photo_path),
        "last_activity_at": (last.created_at if last else row.created_at).isoformat() + "Z"}


async def listing(db, user):
    latest = select(func.max(InquiryMessage.created_at)).where(InquiryMessage.inquiry_id == Inquiry.id).correlate(Inquiry).scalar_subquery()
    rows = (await db.scalars(select(Inquiry).where(or_(Inquiry.buyer_id == user.id, Inquiry.seller_id == user.id),
        Inquiry.linked_deal_id.is_(None), Inquiry.expires_at > datetime.utcnow())
        .where(exists(select(InquiryMessage.id).where(InquiryMessage.inquiry_id == Inquiry.id)))
        .order_by(func.coalesce(latest, Inquiry.created_at).desc(), Inquiry.id).limit(100))).all()
    if not rows: return []
    ids = [row.id for row in rows]
    peer_ids = {row.seller_id if row.buyer_id == user.id else row.buyer_id for row in rows}
    peers = {peer.id:peer for peer in (await db.scalars(select(User).where(User.id.in_(peer_ids)))).all()}
    sellers = {row.id:row for row in (await db.scalars(select(SellerProfile).where(SellerProfile.id.in_([row.seller_profile_id for row in rows])))).all()}
    last = {row.inquiry_id:row for row in (await db.scalars(select(InquiryMessage).where(InquiryMessage.inquiry_id.in_(ids))
        .distinct(InquiryMessage.inquiry_id).order_by(InquiryMessage.inquiry_id, InquiryMessage.created_at.desc(), InquiryMessage.id.desc()))).all()}
    counts = dict((await db.execute(select(InquiryMessage.inquiry_id, func.count()).join(Inquiry, Inquiry.id == InquiryMessage.inquiry_id)
        .where(Inquiry.id.in_(ids), InquiryMessage.sender_id != user.id, or_(
            and_(Inquiry.buyer_id == user.id, or_(Inquiry.buyer_read_at.is_(None), InquiryMessage.created_at > Inquiry.buyer_read_at)),
            and_(Inquiry.seller_id == user.id, or_(Inquiry.seller_read_at.is_(None), InquiryMessage.created_at > Inquiry.seller_read_at))))
        .group_by(InquiryMessage.inquiry_id))).all())
    return [snapshot(row, user, sellers.get(row.seller_profile_id), counts.get(row.id, 0), last.get(row.id),
        peers.get(row.seller_id if row.buyer_id == user.id else row.buyer_id)) for row in rows]


def message_view(row, user):
    return {"id": str(row.id), "mine": row.sender_id == user.id, "text": row.text,
        "photo_url": deal_media.signed_url(row.photo_path) if row.photo_path else None,
        "created_at": row.created_at.isoformat() + "Z"}


async def lock_sender(db, user):
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": user.id.int & ((1 << 63) - 1)})


async def rate_limit(db, user):
    count = await db.scalar(select(func.count()).select_from(InquiryMessage).where(
        InquiryMessage.sender_id == user.id, InquiryMessage.created_at > datetime.utcnow() - timedelta(minutes=1)))
    if count >= 30: raise HTTPException(429, "Слишком много сообщений. Повторите через минуту.")


async def attach_order(db, order, items, deals):
    """Called only inside verified payment completion, in the same transaction."""
    seller_ids = set()
    for item in items:
        try:
            owner = (item.product_snapshot or {}).get("owner_user_id")
            if owner: seller_ids.add(uuid.UUID(str(owner)))
        except (ValueError, TypeError):
            continue
    if any(not (item.product_snapshot or {}).get("owner_user_id") and (item.product_snapshot or {}).get("type") != "subscription" for item in items):
        platform_owner = await db.scalar(select(SellerProfile.user_id).where(SellerProfile.is_platform.is_(True)))
        if platform_owner: seller_ids.add(platform_owner)
    # Consistent lock ordering when a basket contains several sellers.
    for seller_id in sorted(seller_ids):
        row = await db.scalar(select(Inquiry).where(Inquiry.buyer_id == order.user_id,
            Inquiry.seller_id == seller_id, Inquiry.paid_order_id.is_(None), Inquiry.expires_at > datetime.utcnow())
            .with_for_update())
        if not row: continue
        row.paid_order_id = order.id
        row.expires_at = datetime.utcnow() + timedelta(days=await retention_days(db))
        deal = next((d for d in deals if d.seller_id == seller_id), None)
        if not deal: continue
        row.linked_deal_id = deal.id
        messages = (await db.scalars(select(InquiryMessage).where(InquiryMessage.inquiry_id == row.id)
            .order_by(InquiryMessage.created_at, InquiryMessage.id))).all()
        for message in messages:
            db.add(DealMessage(deal_id=deal.id, sender_id=message.sender_id, text=message.text,
                media_type="photo" if message.photo_path else None, media_path=message.photo_path,
                direction=MessageDirection.BUYER_TO_SELLER if message.sender_id == row.buyer_id else MessageDirection.SELLER_TO_BUYER,
                created_at=message.created_at))
        deal.buyer_read_at, deal.seller_read_at = row.buyer_read_at, row.seller_read_at
        await db.execute(delete(InquiryMessage).where(InquiryMessage.inquiry_id == row.id))


async def cleanup(session_factory=AsyncSessionLocal):
    async with session_factory() as db:
        now = datetime.utcnow()
        cutoff = now - timedelta(days=await retention_days(db))
        closed = func.coalesce(Deal.chat_closed_at, Deal.released_at, Deal.refunded_at, Deal.last_message_at, Deal.created_at)
        rows = (await db.scalars(select(Inquiry).outerjoin(Deal, Deal.id == Inquiry.linked_deal_id)
            .where(or_(and_(Inquiry.linked_deal_id.is_(None), Inquiry.expires_at <= now),
                and_(Inquiry.linked_deal_id.is_not(None), or_(Deal.id.is_(None), and_(Deal.chat_closed.is_(True), closed <= cutoff)))))
            .order_by(Inquiry.created_at).limit(50).with_for_update(of=Inquiry, skip_locked=True))).all()
        for row in rows: await erase(db, row)
        await db.commit()
    async with session_factory() as db:
        jobs = (await db.scalars(select(InquiryMediaCleanup).order_by(InquiryMediaCleanup.created_at)
            .limit(20).with_for_update(skip_locked=True))).all()
        folder = deal_media.media_dir().resolve()
        for job in jobs:
            prefix = job.inquiry_id.hex + "_"
            protected = set((await db.scalars(select(DealMessage.media_path).where(DealMessage.media_path.like(prefix + "%")))).all())
            for path in folder.glob(prefix + "*.jpg"):
                target = path.resolve()
                if target.parent == folder and path.name not in protected:
                    target.unlink(missing_ok=True)
            await db.delete(job)
        await db.commit()
