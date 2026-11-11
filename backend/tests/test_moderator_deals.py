"""Moderator queues and access to conversations only after a complaint."""
from datetime import datetime
import pytest
from sqlalchemy import select
from models.p2p import Deal, DealStatus, DealMessage, MessageDirection
from services import deal_service
from test_deals import funded_deal, buyer, seller
from test_http_wiring import client, staff, _bearer

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("status", list(DealStatus))
async def test_moderator_list_cannot_expand_scope(client, db, staff, funded_deal, status):
    admin, moderator, _ = staff
    funded_deal.status = status
    await db.flush()
    mod = _bearer(moderator, role="moderator")
    allowed = status in (DealStatus.DISPUTED, DealStatus.PAID_ESCROW)
    url = "/api/admin/p2p/deals"
    page = (await client.get(url, headers=mod)).json()
    assert page["total"] == (1 if allowed else 0)
    assert len(page["items"]) == (1 if allowed else 0)
    response = await client.get(url, params={"status":status.value}, headers=mod)
    assert response.status_code == (200 if allowed else 403)
    adm = await client.get(url, params={"status":status.value}, headers=_bearer(admin, role="admin"))
    assert adm.status_code == 200 and adm.json()["total"] == 1


@pytest.mark.parametrize("status", [DealStatus.PAID_ESCROW, DealStatus.CHAT_OPENED, DealStatus.DELIVERED_CLAIMED, DealStatus.RELEASED, DealStatus.REFUNDED])
async def test_no_complaint_no_read_or_write_even_by_direct_url(client, db, staff, funded_deal, status):
    admin, moderator, _ = staff
    funded_deal.status = status
    db.add(DealMessage(deal_id=funded_deal.id, sender_id=funded_deal.buyer_id, direction=MessageDirection.BUYER_TO_SELLER, text="Private conversation"))
    await db.flush()
    url = f"/api/admin/p2p/deals/{funded_deal.id}/messages"
    mod = _bearer(moderator, role="moderator")
    assert (await client.get(url, headers=mod)).status_code == 403
    assert (await client.post(url, headers=mod, json={"text":"Unauthorized reply"})).status_code == 403
    result = await client.get(url, headers=_bearer(admin, role="admin"))
    assert result.status_code == 200 and result.json()["messages"][0]["text"] == "Private conversation"


async def test_complaint_unlocks_chat_and_resolved_history(client, db, staff, funded_deal, buyer):
    _, moderator, _ = staff
    mod = _bearer(moderator, role="moderator")
    url = f"/api/admin/p2p/deals/{funded_deal.id}/messages"
    before = (await client.get("/api/admin/p2p/deals", headers=mod)).json()["items"][0]
    assert before["can_view_conversation"] is False
    await deal_service.open_dispute(db, funded_deal, buyer, "Товар не выдан")
    await db.flush()
    assert (await client.get(url, headers=mod)).status_code == 200
    page = (await client.get("/api/admin/p2p/deals", params={"status":"disputed"}, headers=mod)).json()
    assert page["items"][0]["can_view_conversation"] is True
    posted = await client.post(url, headers=mod, json={"text":"Разбираем вашу жалобу"})
    assert posted.status_code == 200, posted.text
    assert posted.json()["from"] == "moderator"
    funded_deal.status = DealStatus.REFUNDED
    await db.flush()
    history = await client.get(url, headers=mod)
    assert history.status_code == 200
    assert history.json()["deal"]["can_write"] is False
    assert (await client.post(url, headers=mod, json={"text":"Closed"})).status_code == 400


async def test_legacy_disputed_deal_without_timestamp_still_accessible(client, db, staff, funded_deal):
    _, moderator, _ = staff
    funded_deal.status = DealStatus.DISPUTED
    funded_deal.dispute_opened_at = None
    await db.flush()
    result = await client.get(f"/api/admin/p2p/deals/{funded_deal.id}/messages", headers=_bearer(moderator,role="moderator"))
    assert result.status_code == 200
