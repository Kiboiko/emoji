"""Private pre-sale chats and transfer of the actual earned platform fee."""
import asyncio
import io
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from PIL import Image
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import settings
from models.inquiry import Inquiry, InquiryMessage, InquiryMediaCleanup
from models.order import OrderItem
from models.p2p import DealMessage, SellerProfile
from models.partner import PartnerAttribution, PartnerCommission, PartnerLink
from models.referral import ReferralTransaction
from models.user import User
from services import deal_service, finance_service as fin, inquiry_service as chats
from services import partner_service, referral_service, settings_service, subscription_service
from test_auth_utils import BOT_TOKEN, make_init_data
from test_deals import AMOUNT, COMMISSION, SELLER_SHARE, buyer, seller, funded_deal
from test_growth import factory
from test_http_wiring import client, staff, _bearer
from test_referrals import order_with_items
from test_subscriptions import channel

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def partner(db, user_factory):
    recipient = await user_factory(username="commission_owner")
    link = PartnerLink(code="sp_test", name="Partner", beneficiary_id=recipient.id, created_by=recipient.id)
    db.add(link)
    await db.flush()
    return recipient, link


async def attribute(db, user, link):
    db.add(PartnerAttribution(buyer_id=user.id, link_id=link.id))
    user.referrer_id = link.beneficiary_id
    await db.flush()


async def store(db, seller):
    return await db.scalar(select(SellerProfile).where(SellerProfile.user_id == seller.id))


async def test_partner_deal_pays_entire_fee_once_and_balances_ledger(db, funded_deal, buyer, seller, partner):
    recipient, link = partner
    await attribute(db, buyer, link)
    assert (await fin.user_account(db, recipient.id, "TON")).balance_minor == 0
    await deal_service.confirm_receipt(db, funded_deal, buyer)
    assert (await fin.user_account(db, seller.id, "TON")).balance_minor == SELLER_SHARE
    assert (await fin.user_account(db, recipient.id, "TON")).balance_minor == COMMISSION
    assert (await fin.platform_account(db, "TON")).balance_minor == 0
    assert not await partner_service.pay_commission(db, buyer_id=buyer.id, order_id=funded_deal.order_id,
        source_kind="deal", source_id=funded_deal.id, amount_nano=COMMISSION)
    assert await db.scalar(select(func.count()).select_from(PartnerCommission)) == 1
    assert (await fin.reconcile(db)).ok
    stats = await referral_service.get_referral_statistics(db, recipient)
    assert Decimal(str(stats["earned_ton"])) == Decimal("0.5")


async def test_refund_does_not_pay_partner(db, funded_deal, buyer, partner):
    recipient, link = partner
    await attribute(db, buyer, link)
    await deal_service._refund_to_buyer(db, funded_deal, reason="cancelled")
    assert (await fin.user_account(db, recipient.id, "TON")).balance_minor == 0
    assert (await fin.user_account(db, buyer.id, "TON")).balance_minor == AMOUNT
    assert await db.scalar(select(func.count()).select_from(PartnerCommission)) == 0


@pytest.mark.parametrize("bp", [0, 300, 10000])
async def test_subscription_actual_fee_zero_three_or_hundred_percent(db, order_factory, user_factory, channel, partner, bp):
    recipient, link = partner
    user = await user_factory()
    await attribute(db, user, link)
    order = await order_factory(user)
    await settings_service.set_setting(db, "commission_subscription_bp", bp)
    platform = await fin.platform_account(db, "TON")
    await fin.deposit_from_external(db, account=platform, amount_minor=10**10,
        ref_type=fin.LedgerRefType.ORDER, ref_id=order.id)
    for _ in range(2):
        await subscription_service.split_subscription_payment(db, channel=channel, order_id=order.id,
            amount_nano=10**10, key_suffix="plan-test")
    fee = 10**10 * bp // 10000
    assert (await fin.user_account(db, recipient.id, "TON")).balance_minor == fee
    assert (await fin.user_account(db, channel.owner_user_id, "TON")).balance_minor == 10**10 - fee
    assert platform.balance_minor == 0
    assert await db.scalar(select(func.count()).select_from(PartnerCommission)) == (1 if bp else 0)
    assert (await fin.reconcile(db)).ok


async def test_special_referral_never_adds_ordinary_l1_l2_and_disabled_link_keeps_attribution(db, user_factory, order_with_items, partner):
    recipient, link = partner
    recipient.referrer_id = (await user_factory()).id
    user = await user_factory()
    await attribute(db, user, link)
    link.enabled = False
    order = await order_with_items(user, [("p2p", "70"), ("subscription", "30")])
    await referral_service.process_referral_commission(db, order, user, received_nano=10**11)
    assert await db.scalar(select(func.count()).select_from(ReferralTransaction)) == 0
    assert await db.scalar(select(func.count()).select_from(PartnerCommission)) == 0
    assert (await partner_service.attribution(db, user.id)).id == link.id


async def test_own_products_keep_l1_and_skip_p2p_subscription_portions(db, user_factory, order_with_items, partner):
    recipient, link = partner
    user = await user_factory()
    await attribute(db, user, link)
    await settings_service.set_setting(db, "referral_l1_bp", 500)
    order = await order_with_items(user, [("product", "20"), ("p2p", "50"), ("subscription", "30")])
    platform = await fin.platform_account(db, "TON")
    await fin.deposit_from_external(db, account=platform, amount_minor=10**11,
        ref_type=fin.LedgerRefType.ORDER, ref_id=order.id)
    for _ in range(2):
        await referral_service.process_referral_commission(db, order, user, received_nano=10**11)
    assert (await fin.user_account(db, recipient.id, "TON")).balance_minor == 10**9
    assert platform.balance_minor == 99 * 10**9
    assert await db.scalar(select(func.count()).select_from(PartnerCommission)) == 1
    assert await db.scalar(select(func.count()).select_from(ReferralTransaction)) == 0


async def test_link_admin_multiple_links_permissions_fixed_recipient(client, staff, partner, monkeypatch):
    admin, moderator, stranger = staff
    recipient, _ = partner
    monkeypatch.setattr(settings, "VITE_BOT_USERNAME", "Example_bot")
    url = "/api/admin/partner-links"
    for headers, status in [({},401), (_bearer(moderator, role="moderator"),403), (_bearer(stranger),403)]:
        assert (await client.get(url, headers=headers)).status_code == status
        assert (await client.post(url, headers=headers, json={"name":"A", "telegram_id":recipient.telegram_id})).status_code == status
    headers = _bearer(admin, role="admin")
    links = []
    for name in ["One", "Two"]:
        response = await client.post(url, headers=headers, json={"name":name,"telegram_id":recipient.telegram_id})
        assert response.status_code == 200, response.text
        links.append(response.json())
    assert links[0]["code"] != links[1]["code"]
    assert links[0]["url"].startswith("https://t.me/Example_bot?startapp=ref_sp_")
    response = await client.patch(f"{url}/{links[0]['id']}", headers=headers,
        json={"enabled":False,"telegram_id":stranger.telegram_id})
    assert response.json()["enabled"] is False
    assert response.json()["telegram_id"] == str(recipient.telegram_id)
    assert (await client.post(url, headers=headers, json={"name":" ","telegram_id":recipient.telegram_id})).status_code == 422
    assert (await client.post(url, headers=headers, json={"name":"Missing","telegram_id":1234})).status_code == 404


async def test_signed_telegram_signup_first_attribution_immutable_disabled_new_signups(db, partner, monkeypatch):
    from routes.auth import authenticate_telegram
    recipient, link = partner
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    init = make_init_data(user={"id":123456,"first_name":"New"})
    result = await authenticate_telegram(init_data=init, referral_code=link.code, db=db)
    user_id = result["user"].id
    assert (await db.get(PartnerAttribution, user_id)).link_id == link.id
    await authenticate_telegram(init_data=init, referral_code="other_link", db=db)
    assert (await db.get(PartnerAttribution, user_id)).link_id == link.id
    link.enabled = False
    await db.flush()
    result2 = await authenticate_telegram(init_data=make_init_data(user={"id":123457,"first_name":"Next"}), referral_code=link.code, db=db)
    assert await db.get(PartnerAttribution, result2["user"].id) is None
    assert (await db.get(User, result2["user"].id)).referrer_id is None


async def test_inquiry_private_unread_idempotency_expiry_and_no_extension(client, db, seller, buyer, user_factory):
    profile = await store(db, seller)
    stranger = await user_factory()
    url = f"/api/inquiries/store/{profile.id}"
    assert (await client.post(url)).status_code == 401
    assert (await client.post(url, headers=_bearer(seller))).status_code == 409
    opened = await client.post(url, headers=_bearer(buyer))
    assert opened.status_code == 200, opened.text
    ident = opened.json()["id"]
    assert (await client.post(url, headers=_bearer(buyer))).json()["id"] == ident
    base = f"/api/inquiries/{ident}"
    for suffix, method in [("","GET"),("/read","POST"),("/messages","POST")]:
        assert (await client.request(method, base+suffix, headers=_bearer(stranger))).status_code == 404
    assert (await client.post(base+"/messages", headers=_bearer(buyer), data={"body":" "})).status_code == 400
    nonce = str(uuid.uuid4())
    data = {"body":"Hello", "client_id":nonce}
    first = await client.post(base+"/messages", headers=_bearer(buyer), data=data)
    assert first.status_code == 200, first.text
    assert (await client.post(base+"/messages", headers=_bearer(buyer), data=data)).json()["id"] == first.json()["id"]
    row = await db.get(Inquiry, uuid.UUID(ident))
    deadline = row.expires_at
    assert timedelta(hours=71,minutes=59) < deadline-datetime.utcnow() < timedelta(hours=72,seconds=1)
    await client.post(base+"/messages", headers=_bearer(seller), data={"body":"Reply"})
    assert row.expires_at == deadline
    own = (await client.get("/api/inquiries", headers=_bearer(buyer))).json()[0]
    assert own["unread"] == 1 and own["last_text"] == "Reply"
    assert not {"buyer_id","seller_id","username","telegram_id"}.intersection(own)
    await client.post(base+"/read", headers=_bearer(buyer))
    assert (await client.get("/api/inquiries", headers=_bearer(buyer))).json()[0]["unread"] == 0
    row.expires_at = datetime.utcnow()-timedelta(seconds=1)
    await db.flush()
    assert (await client.get(base, headers=_bearer(buyer))).status_code == 404
    assert (await client.post(base+"/messages", headers=_bearer(seller), data={"body":"Late"})).status_code == 404
    assert (await client.get("/api/inquiries", headers=_bearer(seller))).json() == []


async def test_inquiry_private_photo_validation_and_physical_cleanup(client, db, seller, buyer, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DEAL_MEDIA_DIR", str(tmp_path))
    row = await chats.open_chat(db, (await store(db, seller)).id, buyer)
    url = f"/api/inquiries/{row.id}/messages"
    assert (await client.post(url, headers=_bearer(buyer), files={"photo":("bad.jpg",b"not image","image/jpeg")})).status_code == 400
    content = io.BytesIO()
    Image.new("RGB",(4,4),"red").save(content,format="PNG")
    result = await client.post(url, headers=_bearer(buyer), files={"photo":("a.png",content.getvalue(),"image/png")})
    assert result.status_code == 200, result.text
    signed = result.json()["photo_url"]
    assert "?" in signed and "/uploads/" not in signed
    assert (await client.get(signed)).status_code == 200
    assert (await client.get(signed.split("?")[0])).status_code != 200
    files = list(tmp_path.glob("*.jpg"))
    assert len(files) == 1
    row.expires_at = datetime.utcnow()-timedelta(seconds=1)
    await db.flush()
    await chats.cleanup(factory(db))
    assert await db.scalar(select(func.count()).select_from(Inquiry)) == 0
    assert await db.scalar(select(func.count()).select_from(InquiryMessage)) == 0
    assert await db.scalar(select(func.count()).select_from(InquiryMediaCleanup)) == 0
    assert not files[0].exists()


async def test_paid_inquiry_moves_messages_into_deal_once_and_cleanup_keeps_evidence(db, funded_deal, buyer, seller, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DEAL_MEDIA_DIR", str(tmp_path))
    row = await chats.open_chat(db, (await store(db, seller)).id, buyer)
    image = tmp_path / f"{row.id.hex}_{uuid.uuid4().hex}.jpg"
    image.write_bytes(b"private evidence")
    db.add(InquiryMessage(inquiry_id=row.id,sender_id=buyer.id,text="Before purchase",photo_path=image.name))
    await db.flush()
    item = OrderItem(product_snapshot={"owner_user_id":str(seller.id)})
    from models.order import Order
    order = await db.get(Order, funded_deal.order_id)
    await chats.attach_order(db,order,[item],[funded_deal])
    await chats.attach_order(db,order,[item],[funded_deal])
    await db.flush()
    assert row.linked_deal_id == funded_deal.id and row.paid_order_id == order.id
    assert await db.scalar(select(func.count()).select_from(InquiryMessage)) == 0
    messages = (await db.scalars(select(DealMessage).where(DealMessage.deal_id==funded_deal.id))).all()
    assert len(messages)==1 and messages[0].media_path==image.name
    assert await chats.listing(db,buyer)==[]
    row.expires_at=datetime.utcnow()-timedelta(days=5)
    await chats.cleanup(factory(db))
    assert await db.get(Inquiry,row.id) is row  # open paid deal is not deleted
    await chats.erase(db,row)  # durable cleanup must preserve copied deal photos
    await db.commit()
    await chats.cleanup(factory(db))
    assert image.exists()
    assert await db.scalar(select(func.count()).select_from(DealMessage))==1


async def test_pagination_same_timestamp_never_loses_or_duplicates_messages(client, db, seller, buyer):
    row=await chats.open_chat(db,(await store(db,seller)).id,buyer)
    at=datetime.utcnow()
    for i in range(55):
        db.add(InquiryMessage(inquiry_id=row.id,sender_id=seller.id,text=str(i),created_at=at))
    await db.flush()
    url=f"/api/inquiries/{row.id}"
    page=(await client.get(url,headers=_bearer(buyer))).json()
    assert page["has_more"] and len(page["messages"])==50
    previous=(await client.get(url+"?before="+page["messages"][0]["id"],headers=_bearer(buyer))).json()
    ids=[m["id"] for m in page["messages"]+previous["messages"]]
    assert not previous["has_more"] and len(ids)==len(set(ids))==55


async def test_concurrent_open_reuses_one_chat(engine):
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    buyer_id,seller_id=uuid.uuid4(),uuid.uuid4()
    async with sessions() as db:
        for ident in (buyer_id,seller_id):
            db.add(User(id=ident,telegram_id=8_000_000_000_000+ident.int%1_000_000_000,
                first_name="Concurrent",referral_code=ident.hex[:20]))
        await db.flush()
        profile=SellerProfile(user_id=seller_id,display_name="Concurrent",payout_wallet="")
        db.add(profile);await db.commit();store_id=profile.id
    async def opening():
        async with sessions() as db:
            row=await chats.open_chat(db,store_id,await db.get(User,buyer_id))
            await db.commit()
            return row.id
    try:
        a,b=await asyncio.gather(opening(),opening())
        assert a==b
    finally:
        async with sessions() as db:
            await db.execute(delete(Inquiry).where(Inquiry.buyer_id==buyer_id))
            await db.execute(delete(SellerProfile).where(SellerProfile.id==store_id))
            await db.execute(delete(User).where(User.id.in_([buyer_id,seller_id])))
            await db.commit()
