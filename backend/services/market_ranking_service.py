"""Weekly frozen rosters. Public projection never contains financial metrics."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, text
from models.market_ranking import RankingPeriod, RankingEntry
from models.p2p import SellerProfile, SellerStatus, Deal, DealStatus
from models.order import OrderItem
from models.review import Review
from models.user import User
from services.money import to_minor


def week_bounds(now):
    local = now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Moscow"))
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return tuple(d.astimezone(timezone.utc).replace(tzinfo=None) for d in [monday, monday + timedelta(days=7)])


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if value else None


async def _calculate(db, period, now):
    entries = (await db.scalars(select(RankingEntry).where(RankingEntry.period_id == period.id))).all()
    sellers = (await db.scalars(select(SellerProfile).where(SellerProfile.id.in_([e.seller_id for e in entries])))).all()
    owners = {s.user_id: s.id for s in sellers}
    volumes = (await db.execute(select(Deal.seller_id, func.sum(OrderItem.price_usdt * OrderItem.quantity), func.count(Deal.id))
        .join(OrderItem, OrderItem.id == Deal.order_item_id).where(Deal.status == DealStatus.RELEASED,
        Deal.released_at >= period.start_at, Deal.released_at < period.end_at, Deal.seller_id.in_(owners))
        .group_by(Deal.seller_id))).all()
    volume = {owners[u]: (to_minor(amount, "USD"), count) for u, amount, count in volumes}
    reviews = (await db.execute(select(Deal.seller_id, func.sum(Review.rating), func.count(Review.id))
        .join(Review, Review.deal_id == Deal.id).where(Deal.status == DealStatus.RELEASED,
        Deal.released_at >= period.start_at, Deal.released_at < period.end_at,
        Review.created_at < min(now, period.end_at), Review.is_fake.is_(False), Review.is_hidden.is_(False),
        Review.user_id == Deal.buyer_id, Review.rating.is_not(None), Deal.seller_id.in_(owners))
        .group_by(Deal.seller_id))).all()
    ratings = {owners[u]: (int(total), count) for u, total, count in reviews}
    max_volume = max([v[0] for v in volume.values()] or [0])
    for entry in entries:
        entry.volume_cents, entry.sales_count = volume.get(entry.seller_id, (0, 0))
        entry.review_sum, entry.review_count = ratings.get(entry.seller_id, (0, 0))
        entry.quality = Decimal(entry.review_sum + 15) / Decimal(entry.review_count + 5)
        entry.score = (Decimal(70) * entry.volume_cents / max_volume if max_volume else Decimal(0)) + Decimal(6) * entry.quality
    entries.sort(key=lambda e: (e.sales_count > 0, e.score, e.volume_cents, e.quality, -e.seller_id.int), reverse=True)
    for rank, entry in enumerate(entries, 1):
        entry.rank = rank
    period.updated_at = now
    if period.end_at <= now:
        period.status, period.closed_at = "closed", now
    await db.flush()


async def refresh(db, now=None):
    now = now or datetime.utcnow()
    await db.execute(text("SELECT pg_advisory_xact_lock(78130001)"))
    opened = (await db.scalars(select(RankingPeriod).where(RankingPeriod.status == "open"))).all()
    for period in opened:
        await _calculate(db, period, now)
    start, end = week_bounds(now)
    # Reconstruct missed complete weeks using the last observed frozen roster.
    # Current participation settings apply only to the new current week.
    latest = await db.scalar(select(RankingPeriod).order_by(RankingPeriod.start_at.desc()).limit(1))
    if latest:
        roster = list((await db.scalars(select(RankingEntry.seller_id).where(RankingEntry.period_id == latest.id))).all())
        cursor = latest.end_at
        while cursor < start:
            recovered = RankingPeriod(start_at=cursor, end_at=cursor + timedelta(days=7))
            db.add(recovered)
            await db.flush()
            db.add_all([RankingEntry(period_id=recovered.id, seller_id=seller_id) for seller_id in roster])
            await db.flush()
            await _calculate(db, recovered, now)
            cursor += timedelta(days=7)
    current = await db.scalar(select(RankingPeriod).where(RankingPeriod.start_at == start))
    if current is None:
        sellers = (await db.scalars(select(SellerProfile).join(User, User.id == SellerProfile.user_id).where(
            SellerProfile.ranking_enabled.is_(True), SellerProfile.is_platform.is_(False),
            SellerProfile.status == SellerStatus.ACTIVE, User.is_blocked.is_(False)))).all()
        if not sellers:
            return None
        current = RankingPeriod(start_at=start, end_at=end)
        db.add(current)
        await db.flush()
        db.add_all([RankingEntry(period_id=current.id, seller_id=s.id) for s in sellers])
        await db.flush()
        await _calculate(db, current, now)
    return current


async def current_period(db):
    start, _ = week_bounds(datetime.utcnow())
    return await db.scalar(select(RankingPeriod).where(RankingPeriod.start_at == start))


async def projection(db, period, admin=False):
    if period is None:
        return {"period": None, "items": []}
    rows = (await db.execute(select(RankingEntry, SellerProfile, User).join(SellerProfile, RankingEntry.seller_id == SellerProfile.id)
        .join(User, User.id == SellerProfile.user_id).where(RankingEntry.period_id == period.id)
        .order_by(RankingEntry.rank))).all()
    from services.review_service import seller_ratings
    visible_ratings = await seller_ratings(db, [owner.id for _, _, owner in rows]) if not admin else {}
    items = []
    for entry, seller, owner in rows:
        if not admin and (not seller.home_visible or seller.status != SellerStatus.ACTIVE or owner.is_blocked):
            continue
        item = {"id": str(seller.id), "name": seller.display_name, "avatar_url": seller.avatar_url,
                "rating": visible_ratings.get(owner.id, (None, 0))[0],
                "rank": entry.rank, "medal": {1:"gold", 2:"silver", 3:"bronze"}.get(entry.rank)}
        if admin:
            item.update(volume_cents=entry.volume_cents, sales_count=entry.sales_count,
                review_count=entry.review_count, quality=str(entry.quality), score=str(entry.score))
        items.append(item)
    return {"period": {"id": str(period.id), "start_at": iso(period.start_at), "end_at": iso(period.end_at),
            "status": period.status, "updated_at": iso(period.updated_at), "formula": period.formula_version}, "items": items}


async def badges(db):
    data = await projection(db, await current_period(db))
    return {item["id"]: {"rank": item["rank"], "medal": item["medal"]} for item in data["items"]}
