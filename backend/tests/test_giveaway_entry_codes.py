"""Entry codes and per-channel checks follow server-verified participation."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from models.giveaway import GiveawayChat, GiveawayEntry
from services import giveaway_service as gifts
from test_growth import giveaway
from test_http_wiring import client, _bearer

pytestmark = pytest.mark.asyncio


async def test_code_hidden_until_all_required_channels_joined(client, db, giveaway, user_factory, monkeypatch):
    user = await user_factory()
    extra = GiveawayChat(giveaway_id=giveaway.id, chat_id=-100456, title='Second channel', join_link='https://t.me/second_channel')
    db.add(extra)
    await db.flush()
    subscribed = {-100123:True, -100456:False}
    async def telegram(method, payload):
        assert method == 'getChatMember' and payload['user_id'] == user.telegram_id
        return {'status':'member' if subscribed[payload['chat_id']] else 'left'}
    monkeypatch.setattr(gifts, 'preflight', AsyncMock())
    monkeypatch.setattr(gifts, '_call', telegram)
    headers = _bearer(user)
    path = f'/api/giveaways/{giveaway.id}'
    initial = (await client.get(path+'/my-entry',headers=headers)).json()
    assert not initial['joined'] and initial['entry_label'] is None
    failed = (await client.post(path+'/join',headers=headers)).json()
    assert not failed['joined'] and failed['entry_label'] is None
    requirements = await gifts.chats(db,giveaway.id)
    assert {check['requirement_id']:check['joined'] for check in failed['checks']} == {
        str(chat.id):subscribed[chat.chat_id] for chat in requirements}
    assert (await client.get(path+'/my-entry',headers=headers)).json()['entry_label'] is None
    entry = await db.scalar(select(GiveawayEntry).where(GiveawayEntry.user_id==user.id))
    entry.checked_at = datetime.utcnow()-timedelta(seconds=11)
    subscribed[-100456] = True
    await db.flush()
    joined = (await client.post(path+'/join',headers=headers)).json()
    assert joined['joined'] and joined['entry_label'].startswith('Участник ')
    reloaded = (await client.get(path+'/my-entry',headers=headers)).json()
    assert reloaded['entry_label'] == joined['entry_label']
    assert (await client.post(path+'/join',headers=headers)).json()['entry_label'] == joined['entry_label']
    await gifts.membership_left(db,-100456,user.telegram_id,datetime.utcnow()+timedelta(seconds=1))
    excluded = (await client.get(path+'/my-entry',headers=headers)).json()
    assert excluded['status']=='excluded' and not excluded['joined'] and excluded['entry_label'] is None


async def test_membership_check_alone_does_not_issue_entry_code(client, db, giveaway, user_factory, monkeypatch):
    user = await user_factory()
    monkeypatch.setattr(gifts,'membership',AsyncMock(return_value=[{'joined':True}]))
    headers = _bearer(user)
    path = f'/api/giveaways/{giveaway.id}'
    response = await client.post(path+'/check-membership',headers=headers)
    assert response.status_code==200
    assert not response.json()['joined'] and response.json()['entry_label'] is None
    assert (await client.get(path+'/my-entry',headers=headers)).json()['entry_label'] is None


async def test_partial_verification_cannot_issue_code(client, db, giveaway, user_factory, monkeypatch):
    user = await user_factory()
    db.add(GiveawayChat(giveaway_id=giveaway.id,chat_id=-100456,title='Second',join_link='https://t.me/second_channel'))
    await db.flush()
    monkeypatch.setattr(gifts,'membership',AsyncMock(return_value=[{'joined':True}]))
    response=await client.post(f'/api/giveaways/{giveaway.id}/join',headers=_bearer(user))
    assert response.status_code==200
    assert not response.json()['joined'] and response.json()['entry_label'] is None
