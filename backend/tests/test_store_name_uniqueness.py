"""Store names share one namespace across registration, rename and channels."""
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.p2p import SellerProfile
from routes import admin_p2p, p2p, subscriptions

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("name", ["Wolf", "WOLF", "wolf", "  WoLf  "])
@pytest.mark.parametrize("operation", ["register", "rename", "platform"])
async def test_existing_store_name_cannot_be_copied(db, user_factory, name, operation):
    owner = await user_factory()
    newcomer = await user_factory()
    original = SellerProfile(user_id=owner.id, display_name="Wolf", payout_wallet="")
    db.add(original)
    await db.flush()

    target = None
    if operation != "register":
        target = SellerProfile(user_id=newcomer.id if operation == "rename" else None,
            display_name="Another Shop", payout_wallet="", name_locked=False,
            is_platform=operation == "platform")
        db.add(target)
        await db.flush()

    with pytest.raises(HTTPException) as caught:
        if operation == "register":
            await p2p.register_seller(p2p.SellerRegister(display_name=name, accept_terms=True), user=newcomer, db=db)
        elif operation == "rename":
            await p2p.update_seller(p2p.SellerUpdate(display_name=name), user=newcomer, db=db)
        else:
            await admin_p2p.update_platform_store(admin_p2p.PlatformStoreUpdate(display_name=name), admin=newcomer, db=db)

    assert caught.value.status_code == 400
    assert "занято" in caught.value.detail
    assert original.display_name == "Wolf"
    if target:
        assert target.display_name == "Another Shop"
        assert not target.name_locked
    else:
        assert await db.scalar(select(SellerProfile.id).where(SellerProfile.user_id == newcomer.id)) is None


async def test_channel_auto_name_does_not_copy_existing_store(db, user_factory):
    owner = await user_factory()
    db.add(SellerProfile(user_id=owner.id, display_name="Wolf", payout_wallet=""))
    await db.flush()

    assert await subscriptions._free_store_name(db, "  WOLF  ") == "WOLF #2"


async def test_saving_own_name_is_allowed(db, user_factory):
    owner = await user_factory()
    store = SellerProfile(user_id=owner.id, display_name="Wolf", payout_wallet="", name_locked=True)
    db.add(store)
    await db.flush()

    result = await p2p.update_seller(p2p.SellerUpdate(display_name="  Wolf  "), user=owner, db=db)
    assert result["display_name"] == "Wolf"
