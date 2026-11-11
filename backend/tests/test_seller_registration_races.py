"""Independent DB sessions: same owner and case-insensitive name collisions."""
import asyncio
import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from models.user import User
from models.p2p import SellerProfile, TermsAcceptance
from routes import p2p

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("same_owner", [True, False])
async def test_registration_races_return_friendly_conflict(engine, monkeypatch, same_owner):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    identifiers = [uuid.uuid4() for _ in range(1 if same_owner else 2)]
    async with sessions() as db:
        for ident in identifiers:
            db.add(User(id=ident, telegram_id=8_000_000_000_000+ident.int%1_000_000_000,
                first_name="Concurrent", username="reg_"+ident.hex[:12], referral_code=ident.hex[:15]))
        await db.commit()
    original = p2p._assert_name_is_free
    barrier = asyncio.Barrier(2)
    if not same_owner:
        async def name_check(*args, **kwargs):
            await original(*args, **kwargs)
            await asyncio.wait_for(barrier.wait(), timeout=5)
        monkeypatch.setattr(p2p, "_assert_name_is_free", name_check)

    async def register(index):
        async with sessions() as db:
            user = await db.get(User, identifiers[0 if same_owner else index])
            try:
                await p2p.register_seller(p2p.SellerRegister(display_name="Race "+identifiers[0].hex[:8], accept_terms=True), user=user, db=db)
                return 200
            except HTTPException as exc:
                return exc.status_code
    try:
        assert sorted(await asyncio.gather(register(0), register(1))) == [200, 400]
        async with sessions() as db:
            rows = (await db.scalars(select(SellerProfile).where(SellerProfile.user_id.in_(identifiers)))).all()
            assert len(rows) == 1
    finally:
        async with sessions() as db:
            await db.execute(delete(SellerProfile).where(SellerProfile.user_id.in_(identifiers)))
            await db.execute(delete(TermsAcceptance).where(TermsAcceptance.user_id.in_(identifiers)))
            await db.execute(delete(User).where(User.id.in_(identifiers)))
            await db.commit()


async def test_concurrent_first_telegram_login_returns_same_user(engine, monkeypatch):
    from config import settings
    from routes.auth import authenticate_telegram
    from test_auth_utils import make_init_data, BOT_TOKEN
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    barrier = asyncio.Barrier(2)
    telegram_id = 8_000_000_000_000 + uuid.uuid4().int % 1_000_000_000

    class RacingSession(AsyncSession):
        waited = False

        async def execute(self, statement, *args, **kwargs):
            result = await super().execute(statement, *args, **kwargs)
            if not self.waited and getattr(statement, "is_select", False) and "users.telegram_id =" in str(statement):
                self.waited = True
                await asyncio.wait_for(barrier.wait(), timeout=5)
            return result

    sessions = async_sessionmaker(engine, class_=RacingSession, expire_on_commit=False)
    init_data = make_init_data(user={"id":telegram_id,"first_name":"Concurrent","language_code":"ru"})
    async def login():
        async with sessions() as db:
            try:
                result = await authenticate_telegram(init_data=init_data, referral_code=None, db=db)
                return 200, str(result["user"].id)
            except HTTPException as exc:
                return exc.status_code, None
    try:
        responses = await asyncio.gather(login(), login())
        assert [status for status, _ in responses] == [200, 200]
        assert responses[0][1] == responses[1][1]
    finally:
        async with async_sessionmaker(engine)() as db:
            await db.execute(delete(User).where(User.telegram_id == telegram_id))
            await db.commit()
