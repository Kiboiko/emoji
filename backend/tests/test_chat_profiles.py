"""Opening without persistence, first-message idempotency and signed profile photos."""
import json
import uuid
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode

import pytest
from sqlalchemy import func, select

from config import settings
from models.inquiry import Inquiry, InquiryMessage
from models.p2p import SellerProfile, DealStatus
from models.user import User
from services import inquiry_service, deal_chat_service
from test_auth_utils import BOT_TOKEN, make_init_data
from test_deals import seller, buyer, funded_deal
from test_http_wiring import client, _bearer

pytestmark = pytest.mark.asyncio


async def store_id(db, seller):
    return await db.scalar(select(SellerProfile.id).where(SellerProfile.user_id == seller.id))


async def test_open_composer_does_not_create_chat_for_either_party(client, db, seller, buyer):
    url = f"/api/inquiries/store/{await store_id(db,seller)}"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=_bearer(seller))).status_code == 409
    for _ in range(3):
        draft = await client.get(url, headers=_bearer(buyer))
        assert draft.status_code == 200 and draft.json()['id'] is None
    assert await db.scalar(select(func.count()).select_from(Inquiry)) == 0
    for user in (seller,buyer):
        assert (await client.get('/api/inquiries', headers=_bearer(user))).json() == []


async def test_first_message_saves_once_and_shows_both_avatars(client, db, seller, buyer):
    buyer.photo_url = 'https://t.me/i/userpic/320/buyer.jpg'
    seller.photo_url = 'https://t.me/i/userpic/320/seller.jpg'
    profile = await db.get(SellerProfile, await store_id(db,seller))
    profile.avatar_url = '/uploads/stores/logo.jpg'
    await db.flush()
    url = f'/api/inquiries/store/{profile.id}'
    preview = (await client.get(url,headers=_bearer(buyer))).json()
    assert preview['avatar_url'] == profile.avatar_url and preview['my_avatar_url'] == buyer.photo_url
    data = {'body':'Question before purchase','client_id':str(uuid.uuid4())}
    first = await client.post(url+'/messages',headers=_bearer(buyer),data=data)
    assert first.status_code == 200,first.text
    retry = await client.post(url+'/messages',headers=_bearer(buyer),data=data)
    assert first.json()['message']['id'] == retry.json()['message']['id']
    assert first.json()['chat']['id'] == retry.json()['chat']['id']
    assert await db.scalar(select(func.count()).select_from(Inquiry)) == 1
    assert await db.scalar(select(func.count()).select_from(InquiryMessage)) == 1
    assert (await client.get(url,headers=_bearer(buyer))).json()['id'] == first.json()['chat']['id']
    for viewer,peer_image,own_image,name in [(buyer,profile.avatar_url,buyer.photo_url,profile.display_name),
                                           (seller,buyer.photo_url,profile.avatar_url,'Покупатель')]:
        row = (await client.get('/api/inquiries',headers=_bearer(viewer))).json()[0]
        assert (row['avatar_url'],row['my_avatar_url'],row['name']) == (peer_image,own_image,name)
        assert not {'buyer_id','seller_id','telegram_id','username'}.intersection(row)


async def test_existing_empty_chat_is_hidden_and_reused_on_first_message(client, db, seller, buyer):
    row = await inquiry_service.open_chat(db,await store_id(db,seller),buyer)
    await db.commit()
    assert (await client.get('/api/inquiries',headers=_bearer(buyer))).json() == []
    base = f'/api/inquiries/store/{row.seller_profile_id}'
    assert (await client.get(base,headers=_bearer(buyer))).json()['id'] is None
    response = await client.post(base+'/messages',headers=_bearer(buyer),data={'body':'First real message'})
    assert response.status_code == 200 and response.json()['chat']['id'] == str(row.id)
    assert len((await client.get('/api/inquiries',headers=_bearer(seller))).json()) == 1


async def test_failed_first_send_leaves_no_chat(client, db, seller, buyer):
    ident = await store_id(db,seller)
    await db.commit()
    url = f'/api/inquiries/store/{ident}/messages'
    headers = _bearer(buyer)
    assert (await client.post(url,headers=headers,data={'body':' '})).status_code == 400
    assert (await client.post(url,headers=headers,files={'photo':('bad.jpg',b'not a photo','image/jpeg')})).status_code == 400
    assert await db.scalar(select(func.count()).select_from(Inquiry)) == 0
    assert await db.scalar(select(func.count()).select_from(InquiryMessage)) == 0


async def test_expired_chat_does_not_reappear_when_opening_composer(client, db, seller, buyer):
    row = await inquiry_service.open_chat(db,await store_id(db,seller),buyer)
    row.expires_at = datetime.utcnow()-timedelta(seconds=1)
    db.add(InquiryMessage(inquiry_id=row.id,sender_id=buyer.id,text='Expired'))
    await db.commit()
    url = f'/api/inquiries/store/{row.seller_profile_id}'
    assert (await client.get(url,headers=_bearer(buyer))).json()['id'] is None
    response = await client.post(url+'/messages',headers=_bearer(buyer),data={'body':'New question'})
    assert response.status_code == 200 and response.json()['chat']['id'] != str(row.id)


async def test_signed_photo_is_refreshed_and_cleared_when_telegram_omits_it(client, db, monkeypatch):
    monkeypatch.setattr(settings,'TELEGRAM_BOT_TOKEN',BOT_TOKEN)
    photo = 'https://t.me/i/userpic/320/buyer.svg'
    user = {'id':8123456,'first_name':'Photo owner','photo_url':photo}
    init = make_init_data(user=user)
    result = await client.post('/api/auth/telegram',headers={'X-Telegram-Init-Data':init})
    assert result.status_code == 200,result.text
    ident = uuid.UUID(result.json()['user']['id'])
    assert (await db.get(User,ident)).photo_url == photo
    fields = {k:v[0] for k,v in parse_qs(init).items()}
    user['photo_url'] = 'https://example.org/forged.jpg'
    fields['user'] = json.dumps(user)
    assert (await client.post('/api/auth/telegram',headers={'X-Telegram-Init-Data':urlencode(fields)})).status_code == 401
    assert (await db.get(User,ident)).photo_url == photo
    user.pop('photo_url')
    assert (await client.post('/api/auth/telegram',headers={'X-Telegram-Init-Data':make_init_data(user=user)})).status_code == 200
    assert (await db.get(User,ident)).photo_url is None


@pytest.mark.parametrize('photo',['javascript:alert(1)','data:image/svg+xml,invalid','http://example.org/a.jpg','https://user:pw@example.org/a.jpg','https://example.org:bad/a.jpg'])
async def test_unsafe_photo_urls_are_not_persisted(client, db, monkeypatch, photo):
    monkeypatch.setattr(settings,'TELEGRAM_BOT_TOKEN',BOT_TOKEN)
    init = make_init_data(user={'id':8123457,'first_name':'Photo','photo_url':photo})
    result = await client.post('/api/auth/telegram',headers={'X-Telegram-Init-Data':init})
    assert result.status_code == 200
    assert (await db.get(User,uuid.UUID(result.json()['user']['id']))).photo_url is None


async def test_paid_chat_photos_for_both_roles_including_closed_deals(db, funded_deal, buyer, seller):
    buyer.photo_url='https://t.me/i/userpic/320/buyer.jpg'
    seller.photo_url='https://t.me/i/userpic/320/seller.jpg'
    await db.flush()
    for status in (DealStatus.PAID_ESCROW,DealStatus.REFUNDED):
        funded_deal.status=status
        for viewer,expected in [(buyer,seller.photo_url),(seller,buyer.photo_url)]:
            dto=(await deal_chat_service.deal_dtos(db,[funded_deal],viewer))[0]
            assert dto['counterpart_avatar_url']==expected
