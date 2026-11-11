from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal
import uuid
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, func
from models.market_ranking import RankingPeriod, RankingEntry
from models.p2p import Deal, DealStatus, SellerProfile
from models.order import OrderItem
from models.review import Review
from models.giveaway import Giveaway, GiveawayChat, GiveawayEntry, GiveawayDrawAttempt
from models.telegram_publication import TelegramPublication
from services import market_ranking_service as ranking, giveaway_service as gifts, telegram_publication_service as posts
from services.telegram_service import TelegramApiError
from test_http_wiring import client, staff, _bearer
from test_deals import funded_deal, buyer, seller
from test_performance import make_product, category

pytestmark = pytest.mark.asyncio


def factory(db):
    @asynccontextmanager
    async def session():
        yield db
    return session


async def test_week_bounds_moscow_and_sunday():
    start, end = ranking.week_bounds(datetime(2026, 11, 1, 22))
    assert start == datetime(2026, 11, 1, 21)  # Monday midnight Moscow
    assert end - start == timedelta(days=7)
    assert ranking.week_bounds(datetime(2026, 11, 1, 20, 59))[1] == start


async def test_ranking_formula_real_reviews_frozen_roster_and_public_privacy(db, user_factory, order_factory):
    owner1, owner2, buyer1 = await user_factory(), await user_factory(), await user_factory()
    s1 = SellerProfile(user_id=owner1.id, display_name="First", payout_wallet="", ranking_enabled=True)
    s2 = SellerProfile(user_id=owner2.id, display_name="Second", payout_wallet="", ranking_enabled=True)
    db.add_all([s1, s2]); await db.flush()
    now = datetime(2026, 11, 4, 12)
    for s, amount in [(s1, "100"), (s2, "50")]:
        order = await order_factory(buyer1)
        item = OrderItem(order_id=order.id, quantity=1, price_usdt=Decimal(amount), product_snapshot={})
        db.add(item); await db.flush()
        deal = Deal(order_id=order.id, order_item_id=item.id, buyer_id=buyer1.id, seller_id=s.user_id,
            product_name="Sale", status=DealStatus.RELEASED, released_at=now - timedelta(hours=1))
        db.add(deal); await db.flush()
    period = await ranking.refresh(db, now)
    entries = (await db.scalars(select(RankingEntry).where(RankingEntry.period_id == period.id).order_by(RankingEntry.rank))).all()
    assert [e.seller_id for e in entries] == [s1.id, s2.id]
    assert entries[0].volume_cents == 10000
    assert entries[0].score == Decimal(88)  # 70 sales + 18 neutral prior
    s1.ranking_enabled = False
    await ranking.refresh(db, now + timedelta(days=1))
    assert await db.scalar(select(func.count()).select_from(RankingEntry).where(RankingEntry.period_id == period.id)) == 2
    public = await ranking.projection(db, period)
    assert all(not {"score", "volume_cents", "sales_count", "quality", "user_id"}.intersection(i) for i in public["items"])
    s1.home_visible = False
    assert len((await ranking.projection(db, period))["items"]) == 1
    await ranking.refresh(db, now + timedelta(days=7))
    assert period.status == "closed"
    original = entries[0].score
    await ranking.refresh(db, now + timedelta(days=8))
    assert entries[0].score == original


async def test_ranking_ignores_escrow_and_fake_hidden_reviews(db, user_factory, order_factory, make_product):
    owner, buyer1 = await user_factory(), await user_factory()
    s = SellerProfile(user_id=owner.id, display_name="Seller", payout_wallet="", ranking_enabled=True)
    db.add(s); await db.flush()
    now = datetime.utcnow()
    product = await make_product()
    for status, stars, fake, hidden in [(DealStatus.RELEASED, 5, False, False),
        (DealStatus.RELEASED, 1, True, False), (DealStatus.RELEASED, 1, False, True),
        (DealStatus.PAID_ESCROW, 1, False, False)]:
        order = await order_factory(buyer1)
        item = OrderItem(order_id=order.id, product_id=product.id, quantity=2, price_usdt=Decimal("5"), product_snapshot={})
        db.add(item); await db.flush()
        deal = Deal(order_id=order.id, order_item_id=item.id, buyer_id=buyer1.id, seller_id=owner.id, product_name="Sale",
            status=status, released_at=now - timedelta(minutes=1))
        db.add(deal); await db.flush()
        db.add(Review(product_id=product.id, deal_id=deal.id, user_id=buyer1.id, rating=stars,
            is_fake=fake, is_hidden=hidden, text="review", created_at=now - timedelta(seconds=5)))
    await db.flush()
    period = await ranking.refresh(db, now)
    entry = await db.scalar(select(RankingEntry).where(RankingEntry.period_id == period.id))
    assert entry.volume_cents == 3000 and entry.sales_count == 3
    assert entry.review_count == 1 and entry.review_sum == 5


async def test_growth_admin_routes_deny_non_admin(client, staff):
    admin, moderator, stranger = staff
    for path in ["/api/admin/market-rankings", "/api/admin/publications", "/api/admin/publications/config", "/api/admin/giveaways"]:
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers=_bearer(moderator, role="moderator"))).status_code == 403
        assert (await client.get(path, headers=_bearer(stranger))).status_code == 403
        assert (await client.get(path, headers=_bearer(admin, role="admin"))).status_code == 200


async def test_publications_disabled_and_atomic_idempotent_event(db, funded_deal):
    deal = funded_deal
    deal.status, deal.released_at = DealStatus.RELEASED, datetime.utcnow()
    await posts.enqueue(db, deal)
    assert await db.scalar(select(func.count()).select_from(TelegramPublication)) == 0
    config = await posts.configuration(db)
    config.enabled, config.chat_id, config.min_nano = True, -100123, 1
    config.enabled_at = datetime.utcnow() - timedelta(hours=1)
    await db.flush()
    await posts.enqueue(db, deal); await posts.enqueue(db, deal)
    rows = (await db.scalars(select(TelegramPublication))).all()
    assert len(rows) == 1
    assert "25 Gram" in rows[0].payload["text"]
    assert not {"buyer_id", "user_id", "content_data"}.intersection(rows[0].payload)


@pytest.mark.parametrize("failure,expected", [(None, "sent"), (TimeoutError(), "unknown"),
    (TelegramApiError("sendMessage", "forbidden", 403), "failed"),
    (TelegramApiError("sendMessage", "slow down", 429, retry_after=90), "retry")])
async def test_publication_delivery_outcomes(db, monkeypatch, failure, expected):
    config = await posts.configuration(db)
    config.enabled, config.chat_id = True, -100123
    row = TelegramPublication(kind="test", source_id=uuid.uuid4(), destination_chat_id=config.chat_id,
        payload={"text":"Public sale"})
    db.add(row); await db.commit()
    send = AsyncMock(side_effect=failure) if failure else AsyncMock(return_value={"message_id": 9})
    monkeypatch.setattr(posts, "send", send)
    await posts.dispatch_one(factory(db))
    await db.refresh(row)
    assert row.status == expected
    if expected in ("unknown", "sent", "failed"):
        await posts.dispatch_one(factory(db))
        assert send.await_count == 1


async def test_expired_sending_becomes_unknown_without_resend(db, monkeypatch):
    row = TelegramPublication(kind="test", source_id=uuid.uuid4(), destination_chat_id=-100123,
        payload={"text":"sale"}, status="sending", lease_until=datetime.utcnow() - timedelta(minutes=1))
    db.add(row); await db.commit()
    send = AsyncMock(); monkeypatch.setattr(posts, "send", send)
    await posts.dispatch_one(factory(db)); await db.refresh(row)
    assert row.status == "unknown" and send.await_count == 0


@pytest.fixture
async def giveaway(db):
    row = Giveaway(title_ru="Приз", title_en="Prize", prize="NFT", start_at=datetime.utcnow() - timedelta(hours=1),
        end_at=datetime.utcnow() + timedelta(hours=1), status="open")
    db.add(row); await db.flush()
    db.add(GiveawayChat(giveaway_id=row.id, chat_id=-100123, title="Required", join_link="https://t.me/required"))
    await db.commit()
    return row


@pytest.mark.parametrize("status,member,allowed", [("member", False, True), ("administrator", False, True),
    ("creator", False, True), ("restricted", True, True), ("restricted", False, False),
    ("left", True, False), ("kicked", True, False)])
async def test_membership_statuses(status, member, allowed):
    assert gifts.member_allowed({"status": status, "is_member": member}) is allowed


async def test_join_identity_deadline_and_duplicate(db, giveaway, user_factory, monkeypatch):
    user = await user_factory()
    verify = AsyncMock(return_value=[{"chat_id":"-100123", "joined":True}])
    monkeypatch.setattr(gifts, "membership", verify)
    assert (await gifts.verify_entry(db, giveaway.id, user, join=True))["joined"]
    assert (await gifts.verify_entry(db, giveaway.id, user, join=True))["joined"]
    assert await db.scalar(select(func.count()).select_from(GiveawayEntry)) == 1
    assert verify.await_count == 1
    giveaway.end_at = datetime.utcnow() - timedelta(seconds=1); await db.commit()
    with pytest.raises(gifts.GiveawayError): await gifts.verify_entry(db, giveaway.id, user, join=True)


async def test_membership_unknown_does_not_join(db, giveaway, user_factory, monkeypatch):
    user = await user_factory()
    monkeypatch.setattr(gifts, "membership", AsyncMock(side_effect=TimeoutError()))
    with pytest.raises(gifts.GiveawayError): await gifts.verify_entry(db, giveaway.id, user, join=True)
    entry = await db.scalar(select(GiveawayEntry))
    assert entry.entered_at is None


async def test_draw_resumes_same_candidate_and_never_rerolls_winner(db, giveaway, user_factory, monkeypatch):
    users = [await user_factory(), await user_factory()]
    giveaway.end_at = datetime.utcnow() - timedelta(seconds=1)
    entries = [GiveawayEntry(giveaway_id=giveaway.id, user_id=u.id, status="joined", entered_at=datetime.utcnow()-timedelta(minutes=10)) for u in users]
    db.add_all(entries); await db.commit()
    monkeypatch.setattr(gifts.secrets, "randbelow", lambda count: 0)
    unavailable = AsyncMock(side_effect=TimeoutError()); monkeypatch.setattr(gifts, "membership", unavailable)
    await gifts.draw_one(giveaway.id, factory(db)); await db.refresh(giveaway)
    selected = await db.scalar(select(GiveawayDrawAttempt))
    assert giveaway.status == "waiting_for_telegram" and selected.status == "selected"
    entry_id = selected.entry_id
    giveaway.lease_until = None; await db.commit()
    available = AsyncMock(return_value=[{"joined":True}]); monkeypatch.setattr(gifts, "membership", available)
    await gifts.draw_one(giveaway.id, factory(db)); await db.refresh(giveaway)
    assert giveaway.status == "finished" and giveaway.winner_user_id is not None
    assert await db.scalar(select(func.count()).select_from(GiveawayDrawAttempt)) == 1
    winner = giveaway.winner_user_id
    await gifts.draw_one(giveaway.id, factory(db))
    assert giveaway.winner_user_id == winner and available.await_count == 1
    assert (await db.get(GiveawayEntry, entry_id)).status == "winner"


async def test_draw_excludes_departed_then_finishes_empty(db, giveaway, user_factory, monkeypatch):
    user = await user_factory()
    giveaway.end_at = datetime.utcnow() - timedelta(seconds=1)
    db.add(GiveawayEntry(giveaway_id=giveaway.id, user_id=user.id, status="joined", entered_at=datetime.utcnow()-timedelta(minutes=10)))
    await db.commit()
    monkeypatch.setattr(gifts, "membership", AsyncMock(return_value=[{"joined":False}]))
    await gifts.draw_one(giveaway.id, factory(db)); await gifts.draw_one(giveaway.id, factory(db)); await db.refresh(giveaway)
    assert giveaway.status == "finished" and giveaway.winner_user_id is None


async def test_published_giveaway_immutable_and_public_winner_private(client, db, staff, giveaway):
    admin, moderator, stranger = staff
    giveaway.status, giveaway.winner_user_id, giveaway.public_winner_label = "finished", stranger.id, "Участник abcdef12"
    await db.commit()
    response = await client.get(f"/api/giveaways/{giveaway.id}")
    assert response.status_code == 200
    assert not {"winner_user_id", "snapshot_hash", "error_code"}.intersection(response.json())
    assert "chat_id" not in response.json()["requirements"][0]
    assert (await client.post(f"/api/admin/giveaways/{giveaway.id}/cancel", headers=_bearer(admin, role="admin"))).status_code == 409
    assert (await client.post(f"/api/admin/giveaways/{giveaway.id}/fulfilled", headers=_bearer(moderator, role="moderator"))).status_code == 403
    assert (await client.get(f"/api/admin/giveaways/{giveaway.id}/draw-attempts", headers=_bearer(moderator, role="moderator"))).status_code == 403
    assert (await client.get(f"/api/admin/giveaways/{giveaway.id}/draw-attempts", headers=_bearer(admin, role="admin"))).json() == []


async def test_due_giveaways_skip_active_leases(db, giveaway):
    giveaway.end_at = datetime.utcnow() - timedelta(seconds=1)
    giveaway.lease_until = datetime.utcnow() + timedelta(minutes=1)
    await db.flush()
    assert giveaway.id not in await gifts.due_giveaways(db)
    giveaway.lease_until = datetime.utcnow() - timedelta(seconds=1)
    await db.flush()
    assert giveaway.id in await gifts.due_giveaways(db)


async def test_ranking_catches_up_missing_weeks(db, user_factory):
    owner = await user_factory()
    seller = SellerProfile(user_id=owner.id, display_name="Roster", payout_wallet="", ranking_enabled=True)
    db.add(seller); await db.flush()
    now = datetime(2026, 11, 4, 12)
    await ranking.refresh(db, now)
    await ranking.refresh(db, now + timedelta(days=22))
    periods = (await db.scalars(select(RankingPeriod).order_by(RankingPeriod.start_at))).all()
    assert len(periods) == 4
    assert [p.status for p in periods] == ["closed", "closed", "closed", "open"]
    assert all(periods[i].end_at == periods[i + 1].start_at for i in range(3))
    await ranking.refresh(db, now + timedelta(days=22))
    assert await db.scalar(select(func.count()).select_from(RankingPeriod)) == 4


async def test_publication_and_funds_rollback_together(db, funded_deal):
    from services.deal_service import _release_to_seller
    config = await posts.configuration(db)
    config.enabled, config.chat_id, config.min_nano = True, -100123, 1
    config.enabled_at = datetime.utcnow() - timedelta(minutes=5)
    await db.commit()
    with pytest.raises(RuntimeError):
        async with db.begin_nested():
            await _release_to_seller(db, funded_deal, reason="buyer confirmed")
            assert await db.scalar(select(func.count()).select_from(TelegramPublication)) == 1
            raise RuntimeError("abort transaction")
    await db.refresh(funded_deal)
    assert funded_deal.status == DealStatus.PAID_ESCROW
    assert await db.scalar(select(func.count()).select_from(TelegramPublication)) == 0


async def test_giveaway_http_publish_locks_rules_and_uses_authenticated_identity(client, db, staff, monkeypatch):
    admin, _, user = staff
    body = {"title_ru":"Приз", "title_en":"Prize", "prize":"NFT", "start_at":"2020-01-01T00:00:00Z",
        "end_at":"2030-01-01T00:00:00Z", "requirements":[{"chat_id":-100123, "title":"Required", "join_link":"https://t.me/required"}]}
    created = await client.post("/api/admin/giveaways", headers=_bearer(admin, role="admin"), json=body)
    assert created.status_code == 200
    ident = created.json()["id"]
    assert (await client.get(f"/api/giveaways/{ident}")).status_code == 404
    monkeypatch.setattr(gifts, "preflight", AsyncMock())
    assert (await client.post(f"/api/admin/giveaways/{ident}/publish", headers=_bearer(admin, role="admin"))).status_code == 200
    assert (await client.put(f"/api/admin/giveaways/{ident}", headers=_bearer(admin, role="admin"), json=body)).status_code == 409
    monkeypatch.setattr(gifts, "membership", AsyncMock(return_value=[{"joined":True}]))
    joined = await client.post(f"/api/giveaways/{ident}/join", headers=_bearer(user), json={"user_id":str(admin.id)})
    assert joined.status_code == 200 and joined.json()["joined"]
    entry = await db.scalar(select(GiveawayEntry).where(GiveawayEntry.giveaway_id == uuid.UUID(ident)))
    assert entry.user_id == user.id


async def test_concurrent_draw_workers_choose_once(engine, monkeypatch):
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import delete
    from models.user import User
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, giveaway_id = uuid.uuid4(), uuid.uuid4()
    async with sessions() as db:
        db.add(User(id=user_id, telegram_id=8_000_000_000_000 + secrets_number(), first_name="Concurrency",
            username="growth_" + user_id.hex[:12], referral_code=user_id.hex[:15]))
        db.add(Giveaway(id=giveaway_id, title_ru="Приз", title_en="Prize", prize="NFT", status="open",
            start_at=datetime.utcnow()-timedelta(hours=1), end_at=datetime.utcnow()-timedelta(minutes=1)))
        await db.flush()
        db.add(GiveawayEntry(giveaway_id=giveaway_id, user_id=user_id, status="joined", entered_at=datetime.utcnow()-timedelta(minutes=10)))
        db.add(GiveawayChat(giveaway_id=giveaway_id, chat_id=-100123, title="Chat", join_link="https://t.me/test"))
        await db.commit()
    async def available(*args):
        await asyncio.sleep(.05)
        return [{"joined":True}]
    verified = AsyncMock(side_effect=available)
    monkeypatch.setattr(gifts, "membership", verified)
    try:
        result = await asyncio.gather(gifts.draw_one(giveaway_id, sessions), gifts.draw_one(giveaway_id, sessions))
        assert sum(bool(v) for v in result) == 1
        async with sessions() as db:
            row = await db.get(Giveaway, giveaway_id)
            assert row.status == "finished" and row.winner_user_id == user_id
            assert await db.scalar(select(func.count()).select_from(GiveawayDrawAttempt).where(GiveawayDrawAttempt.giveaway_id == giveaway_id)) == 1
        assert verified.await_count == 1
    finally:
        async with sessions() as db:
            for model in [GiveawayDrawAttempt, GiveawayEntry, GiveawayChat]:
                await db.execute(delete(model).where(model.giveaway_id == giveaway_id))
            await db.execute(delete(Giveaway).where(Giveaway.id == giveaway_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


def secrets_number():
    return uuid.uuid4().int % 1_000_000_000
