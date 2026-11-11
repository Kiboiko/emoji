from datetime import datetime, timedelta
from unittest.mock import AsyncMock
import uuid
import pytest
from sqlalchemy import select, func
from models.giveaway import Giveaway, GiveawayEntry, GiveawayChat, GiveawayDrawAttempt, GiveawayPostCleanup
from services import giveaway_service as gifts, giveaway_lifecycle as life, nft_preview
from services.telegram_service import TelegramApiError
from routes.internal import ChatMemberEvent, handle_chat_member
from test_growth import giveaway, factory
from test_http_wiring import client, staff, _bearer

pytestmark = pytest.mark.asyncio


async def entry(db, giveaway, user_factory):
    user = await user_factory(first_name="Winner", username="winner_handle")
    item = GiveawayEntry(giveaway_id=giveaway.id, user_id=user.id, status="joined",
        entered_at=datetime.utcnow() - timedelta(minutes=10), checked_at=datetime.utcnow() - timedelta(minutes=10))
    db.add(item)
    await db.commit()
    return user, item


async def test_departure_in_giveaway_only_chat_and_restricted_member(db, giveaway, user_factory):
    user, item = await entry(db, giveaway, user_factory)
    await handle_chat_member(ChatMemberEvent(chat_id=-100123, telegram_user_id=user.telegram_id,
        new_status="restricted", is_member=True), db=db)
    assert item.status == "joined"
    await handle_chat_member(ChatMemberEvent(chat_id=-100123, telegram_user_id=user.telegram_id,
        new_status="restricted", is_member=False), db=db)
    await db.refresh(item)
    assert item.status == "excluded" and item.eligibility_version == 1
    assert item.error_code == "unsubscribed"


async def test_old_departure_cannot_remove_later_admission(db, giveaway, user_factory):
    user, item = await entry(db, giveaway, user_factory)
    assert await gifts.membership_left(db, -100123, user.telegram_id, item.entered_at - timedelta(seconds=1)) == 0
    assert item.status == "joined"


async def test_periodic_check_excludes_departed_and_explicit_rejoin_is_required(db, giveaway, user_factory, monkeypatch):
    user, item = await entry(db, giveaway, user_factory)
    verify = AsyncMock(return_value=[{"joined": False}])
    monkeypatch.setattr(gifts, "membership", verify)
    await gifts.recheck_entries(factory(db))
    assert item.status == "excluded"
    item.checked_at = datetime.utcnow() - timedelta(seconds=20)
    verify.return_value = [{"joined": True}]
    await db.commit()
    result = await gifts.verify_entry(db, giveaway.id, user)
    assert not result["joined"]
    item.checked_at = datetime.utcnow() - timedelta(seconds=20)
    await db.commit()
    assert (await gifts.verify_entry(db, giveaway.id, user, join=True))["joined"]


async def test_departure_during_join_cannot_be_overwritten(db, giveaway, user_factory, monkeypatch):
    user = await user_factory()
    async def verify(*args):
        await gifts.membership_left(db, -100123, user.telegram_id)
        await db.commit()
        return [{"joined": True}]
    monkeypatch.setattr(gifts, "membership", verify)
    with pytest.raises(gifts.GiveawayError, match="изменилась"):
        await gifts.verify_entry(db, giveaway.id, user, join=True)
    item = await db.scalar(select(GiveawayEntry).where(GiveawayEntry.user_id == user.id))
    assert item.status == "excluded"


async def test_winner_name_username_and_only_eligible_entries_public(client, db, giveaway, user_factory, monkeypatch):
    user, item = await entry(db, giveaway, user_factory)
    giveaway.end_at = datetime.utcnow() - timedelta(seconds=1)
    await db.commit()
    monkeypatch.setattr(gifts, "membership", AsyncMock(return_value=[{"joined": True}]))
    await gifts.draw_one(giveaway.id, factory(db))
    response = await client.get(f"/api/giveaways/{giveaway.id}")
    body = response.json()
    assert body["winner"] == "Winner" and body["winner_username"] == "winner_handle"
    assert "winner_user_id" not in body and str(user.id) not in response.text
    assert body["participants"] == 1


async def test_cancellation_deletes_all_game_records_and_queues_post_erasure(client, db, staff, giveaway, user_factory):
    admin, _, _ = staff
    user, item = await entry(db, giveaway, user_factory)
    giveaway.post_chat_id, giveaway.post_message_id, giveaway.post_status = -100987, 7, "sent"
    attempt = GiveawayDrawAttempt(giveaway_id=giveaway.id, entry_id=item.id, ordinal=1)
    db.add(attempt)
    await db.commit()
    ident = giveaway.id
    response = await client.post(f"/api/admin/giveaways/{ident}/cancel", headers=_bearer(admin, role="admin"))
    assert response.status_code == 200
    for model in (Giveaway, GiveawayEntry, GiveawayChat, GiveawayDrawAttempt):
        assert await db.scalar(select(func.count()).select_from(model)) == 0
    cleanup = await db.scalar(select(GiveawayPostCleanup))
    assert cleanup.chat_id == -100987 and cleanup.message_id == 7
    assert (await client.get(f"/api/giveaways/{ident}")).status_code == 404
    assert (await client.get("/api/admin/giveaways", headers=_bearer(admin, role="admin"))).json() == []


async def test_retention_hides_and_deletes_finished_after_30_days(client, db, giveaway):
    giveaway.status = "finished"
    giveaway.finished_at = datetime.utcnow() - timedelta(days=31)
    recent = Giveaway(title_ru="Recent", title_en="Recent", prize="NFT", status="finished",
        start_at=datetime.utcnow()-timedelta(days=32), end_at=datetime.utcnow()-timedelta(days=29),
        finished_at=datetime.utcnow()-timedelta(days=29))
    db.add(recent)
    await db.commit()
    ident = giveaway.id
    assert [row["id"] for row in (await client.get("/api/giveaways")).json()] == [str(recent.id)]
    assert (await client.get(f"/api/giveaways/{ident}")).status_code == 404
    await life.purge(factory(db))
    assert await db.get(Giveaway, ident) is None
    assert await db.get(Giveaway, recent.id) is not None


async def test_post_sends_one_deep_link_and_never_retries_unknown(db, giveaway, monkeypatch):
    monkeypatch.setattr(life.settings, "VITE_BOT_USERNAME", "Example_bot")
    giveaway.post_status, giveaway.post_chat_id = "queued", -100987
    await db.commit()
    send = AsyncMock(return_value={"message_id": 9})
    monkeypatch.setattr(life, "_call", send)
    assert await life.dispatch_post(factory(db))
    assert giveaway.post_status == "sent" and giveaway.post_message_id == 9
    payload = send.call_args.args[1]
    assert payload['text'].startswith('Giveaway\n')
    assert payload['text'].count('Giveaway') == 1
    assert payload['entities'] == [{'type':'bold','offset':0,'length':8}]
    assert payload["reply_markup"]["inline_keyboard"][0][0]["url"].endswith("giveaway_" + giveaway.id.hex)
    assert not await life.dispatch_post(factory(db))
    assert send.await_count == 1
    giveaway.post_status, giveaway.post_message_id = "queued", None
    await db.commit()
    send.side_effect = TimeoutError()
    assert await life.dispatch_post(factory(db))
    assert giveaway.post_status == "unknown"
    assert not await life.dispatch_post(factory(db))
    assert send.await_count == 2


async def test_nft_post_uses_native_preview_and_preserves_app_photo(db, giveaway, monkeypatch):
    monkeypatch.setattr(life.settings, 'VITE_BOT_USERNAME', 'Example_bot')
    monkeypatch.setattr(life.settings, 'SITE_URL', 'https://example.test')
    giveaway.post_status, giveaway.post_chat_id = 'queued', -100987
    giveaway.photo_url = '/uploads/giveaways/gift.jpg'
    giveaway.prize = 'https://t.me/nft/ValentineBox-29850'
    await db.commit()
    preview = AsyncMock(return_value=('/uploads/giveaways/fresh-nft.jpg', 'Gift'))
    monkeypatch.setattr(nft_preview, 'save_preview', preview)
    send = AsyncMock(return_value={'message_id': 10})
    monkeypatch.setattr(life, '_call', send)
    assert await life.dispatch_post(factory(db))
    method, payload = send.call_args.args
    assert method == 'sendMessage' and 'photo' not in payload and 'caption' not in payload
    assert giveaway.photo_url == '/uploads/giveaways/gift.jpg'
    preview.assert_not_awaited()
    assert payload['link_preview_options'] == {'is_disabled':False,'url':giveaway.prize,
        'prefer_large_media':True,'show_above_text':False}
    assert payload['text'].startswith('Giveaway\n\n' + giveaway.prize)
    assert payload['text'].count('Giveaway') == 1
    assert payload['entities'] == [{'type':'bold','offset':0,'length':8},
        {'type':'url','offset':10,'length':len(giveaway.prize)}]
    assert 'Окончание:' in payload['text'] and 'Участие бесплатное.' in payload['text']
    assert payload['reply_markup']['inline_keyboard'][0][0]['text'] == 'Участвовать'


async def test_admin_can_save_giveaway_without_localized_titles(client, staff):
    now = datetime.utcnow()
    body = {'prize':'NFT', 'start_at':now.isoformat()+'Z',
        'end_at':(now+timedelta(days=1)).isoformat()+'Z',
        'requirements':[{'chat_id':-100123,'title':'Channel','join_link':'https://t.me/channel'}]}
    response = await client.post('/api/admin/giveaways',headers=_bearer(staff[0],role='admin'),json=body)
    assert response.status_code == 200
    row=response.json()
    assert row['title_ru'] == row['title_en'] == 'Giveaway'
    assert row['prize'] == 'NFT' and row['status'] == 'draft'


async def test_old_bot_post_is_scrubbed_when_delete_forbidden(db, monkeypatch):
    job = GiveawayPostCleanup(chat_id=-100987, message_id=9, has_photo=1)
    db.add(job); await db.commit()
    send = AsyncMock(side_effect=[TelegramApiError("deleteMessage", "Bad Request: message can't be deleted", 400),
        TelegramApiError("editMessageText", "Bad Request: there is no text in the message to edit", 400), True])
    monkeypatch.setattr(life, "_call", send)
    await life.erase_posts(factory(db))
    assert await db.scalar(select(func.count()).select_from(GiveawayPostCleanup)) == 0
    assert send.call_args.args[0] == "editMessageMedia"
    assert send.call_args.args[1]["reply_markup"] == {"inline_keyboard": []}
    assert send.call_args.args[1]["media"]["caption"] == "Розыгрыш недоступен."


async def test_native_nft_post_cleanup_removes_preview_and_button(db, monkeypatch):
    job = GiveawayPostCleanup(chat_id=-100987, message_id=9, has_photo=1)
    db.add(job); await db.commit()
    send = AsyncMock(side_effect=[TelegramApiError('deleteMessage', "message can't be deleted", 400), True])
    monkeypatch.setattr(life, '_call', send)
    await life.erase_posts(factory(db))
    assert await db.scalar(select(func.count()).select_from(GiveawayPostCleanup)) == 0
    assert send.call_args.args == ('editMessageText', {'chat_id':-100987,'message_id':9,
        'text':'Розыгрыш недоступен.','link_preview_options':{'is_disabled':True},
        'reply_markup':{'inline_keyboard':[]}})


async def test_non_nft_photo_post_still_uses_uploaded_photo(db, giveaway, monkeypatch):
    monkeypatch.setattr(life.settings, 'VITE_BOT_USERNAME', 'Example_bot')
    monkeypatch.setattr(life.settings, 'SITE_URL', 'https://example.test')
    giveaway.post_status, giveaway.post_chat_id = 'queued', -100987
    giveaway.photo_url = '/uploads/giveaways/manual.jpg'
    await db.commit()
    send = AsyncMock(return_value={'message_id':10})
    monkeypatch.setattr(life, '_call', send)
    await life.dispatch_post(factory(db))
    method,payload=send.call_args.args
    assert method=='sendPhoto' and payload['photo']=='https://example.test/uploads/giveaways/manual.jpg'
    assert payload['show_caption_above_media'] is True and 'link_preview_options' not in payload


@pytest.mark.parametrize("url", ["http://t.me/nft/Pepe-1", "https://127.0.0.1/nft/Pepe-1", "https://t.me.evil.test/nft/Pepe-1", "https://user@t.me/nft/Pepe-1", "https://t.me/nft/../x"])
async def test_nft_page_import_rejects_arbitrary_destinations(url):
    with pytest.raises(ValueError): nft_preview.gift_url(url)


@pytest.mark.parametrize("url", ["http://cdn4.telesco.pe/x", "https://cdn4.telesco.pe.evil.test/x", "https://127.0.0.1/x", "https://user@cdn4.telesco.pe/x", "https://cdn4.telesco.pe:8000/x"])
async def test_nft_preview_rejects_unsafe_image_links(url):
    with pytest.raises(ValueError): nft_preview.image_url(url)


async def test_nft_link_normalization_never_uses_query_as_destination():
    assert nft_preview.gift_url(' https://t.me/nft/Gift-29850/?url=http://localhost#preview ') == 'https://t.me/nft/Gift-29850'


@pytest.mark.parametrize('old_photo', [None, '/uploads/giveaways/old-thumb.jpg', '/uploads/giveaways/other-gift.jpg'])
async def test_saving_nft_without_browser_preview_imports_photo(client, db, staff, monkeypatch, old_photo):
    from routes import giveaways as routes
    admin, _, _ = staff
    preview = AsyncMock(return_value=('/uploads/giveaways/imported.jpg', 'Gift'))
    monkeypatch.setattr(nft_preview, 'save_preview', preview)
    # The mock replaces disk persistence too; identify its returned URL as
    # already imported when create/publish checks it again.
    monkeypatch.setattr(nft_preview, 'current_preview', lambda link, url: url == '/uploads/giveaways/imported.jpg')
    now = datetime.utcnow()
    body = {'title_ru':'Giveaway', 'title_en':'Giveaway', 'prize':'29850',
        'nft_link':'https://t.me/nft/Gift-29850/', 'photo_url':old_photo,
        'start_at':now.isoformat()+'Z', 'end_at':(now+timedelta(days=1)).isoformat()+'Z',
        'requirements':[{'chat_id':-100123, 'title':'Channel', 'join_link':'https://t.me/channel'}]}
    headers = _bearer(admin, role='admin')
    response = await client.post('/api/admin/giveaways', headers=headers, json=body)
    assert response.status_code == 200
    row = response.json()
    assert row['prize'] == 'https://t.me/nft/Gift-29850'
    assert row['photo_url'] == '/uploads/giveaways/imported.jpg'
    preview.assert_awaited_once_with('https://t.me/nft/Gift-29850')
    assert (await client.get('/api/giveaways')).json() == []  # Still a draft.
    monkeypatch.setattr(routes.service, 'preflight', AsyncMock())
    published = await client.post('/api/admin/giveaways/'+row['id']+'/publish', headers=headers)
    assert published.status_code == 200 and published.json()['photo_url'] == row['photo_url']
    assert (await client.get('/api/giveaways')).json()[0]['photo_url'] == row['photo_url']


async def test_nft_import_failure_does_not_create_blank_giveaway(client, db, staff, monkeypatch):
    monkeypatch.setattr(nft_preview, 'save_preview', AsyncMock(side_effect=ValueError('no preview')))
    now = datetime.utcnow()
    body = {'title_ru':'Gift', 'title_en':'Gift', 'prize':'https://t.me/nft/Gift-1',
        'start_at':now.isoformat()+'Z', 'end_at':(now+timedelta(days=1)).isoformat()+'Z',
        'requirements':[{'chat_id':-100123, 'title':'Channel', 'join_link':'https://t.me/channel'}]}
    response = await client.post('/api/admin/giveaways', headers=_bearer(staff[0],role='admin'), json=body)
    assert response.status_code == 400 and 'фото NFT' in response.json()['detail']
    assert await db.scalar(select(func.count()).select_from(Giveaway)) == 0


@pytest.mark.parametrize('old_photo', [None, '/uploads/giveaways/old-thumb.jpg'])
async def test_publishing_legacy_draft_imports_missing_nft_photo(client, db, staff, giveaway, monkeypatch, old_photo):
    from routes import giveaways as routes
    giveaway.status = 'draft'
    giveaway.prize = 'https://t.me/nft/Gift-29850'
    giveaway.photo_url = old_photo
    await db.flush()
    preview = AsyncMock(side_effect=ValueError('temporary failure'))
    monkeypatch.setattr(nft_preview, 'save_preview', preview)
    monkeypatch.setattr(routes.service, 'preflight', AsyncMock())
    headers = _bearer(staff[0],role='admin')
    path = '/api/admin/giveaways/'+str(giveaway.id)+'/publish'
    assert (await client.post(path, headers=headers)).status_code == 400
    await db.refresh(giveaway)
    assert giveaway.status == 'draft' and giveaway.photo_url == old_photo
    preview.side_effect = None
    preview.return_value = ('/uploads/giveaways/recovered.jpg', 'Gift')
    result = await client.post(path, headers=headers)
    assert result.status_code == 200 and result.json()['photo_url'] == '/uploads/giveaways/recovered.jpg'


async def test_nft_metadata_and_admin_import(client, staff, monkeypatch, tmp_path):
    from routes import giveaways as routes
    admin, moderator, _ = staff
    metadata = nft_preview.Metadata()
    metadata.feed('<meta property="og:title" content="Gift &amp; Star"><meta property="og:image" content="https://cdn4.telesco.pe/file/a.jpg">')
    assert metadata.values["og:title"] == "Gift & Star"
    monkeypatch.setattr(nft_preview, "import_preview", AsyncMock(return_value=(b"prepared-image", ".jpg", "Gift")))
    monkeypatch.setattr(routes.settings, "UPLOAD_DIR", str(tmp_path))
    path = "/api/admin/giveaways/photo-from-nft"
    assert (await client.post(path, headers=_bearer(moderator, role="moderator"), json={"url":"https://t.me/nft/Gift-1"})).status_code == 403
    result = await client.post(path, headers=_bearer(admin, role="admin"), json={"url":"https://t.me/nft/Gift-1"})
    assert result.status_code == 200 and result.json()["title"] == "Gift"
    assert (tmp_path / "giveaways" / result.json()["url"].split('/')[-1]).read_bytes() == b"prepared-image"


async def test_publication_channel_selection_checks_admin_and_bot_rights(client, staff, monkeypatch):
    from services import telegram_service as transport
    admin, moderator, stranger = staff
    payload = {"channel": "@test_channel"}
    for user, role in [(moderator, 'moderator'), (stranger, 'user')]:
        headers = _bearer(user, role=role)
        assert (await client.get('/api/admin/giveaways/post-channels', headers=headers)).status_code == 403
        assert (await client.post('/api/admin/giveaways/resolve-post-channel', headers=headers, json=payload)).status_code == 403
    headers = _bearer(admin, role='admin')
    call = AsyncMock(return_value={"id": -100123, "type": "channel", "title": "Test", "username": "test_channel"})
    rights = AsyncMock()
    monkeypatch.setattr(transport, '_call', call)
    monkeypatch.setattr(life, 'check_post_target', rights)
    response = await client.post('/api/admin/giveaways/resolve-post-channel', headers=headers, json=payload)
    assert response.status_code == 200 and response.json()['chat_id'] == '-100123'
    rights.assert_awaited_once_with(-100123)
    rights.side_effect = ValueError('missing rights')
    assert (await client.post('/api/admin/giveaways/resolve-post-channel', headers=headers, json=payload)).status_code == 400
    assert (await client.post('/api/admin/giveaways/resolve-post-channel', headers=headers, json={"channel": "https://example.com"})).status_code == 422


async def test_nft_download_is_bounded_and_never_follows_redirects(monkeypatch):
    import httpx
    import io
    from PIL import Image
    picture = io.BytesIO()
    Image.new("RGB", (640, 640), "blue").save(picture, format="PNG")
    seen = []
    mode = "ok"
    def respond(request):
        seen.append(str(request.url))
        if request.url.host == "t.me":
            if mode == "redirect":
                return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
            if mode == "large":
                return httpx.Response(200, content=b"a" * 1_000_001)
            return httpx.Response(200, text='<meta property="og:title" content="Gift"><meta property="og:image" content="https://cdn4.telesco.pe/file/a.png">')
        if request.url.host == "nft.fragment.com":
            return httpx.Response(404)
        return httpx.Response(200, content=picture.getvalue())
    real_client = httpx.AsyncClient
    monkeypatch.setattr(nft_preview.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    data, extension, title = await nft_preview.import_preview("https://t.me/nft/Gift-1")
    assert title == "Gift" and extension == ".jpg" and Image.open(io.BytesIO(data)).size == (640, 640)
    assert len(seen) == 3
    mode = "redirect"; seen.clear()
    with pytest.raises(httpx.HTTPStatusError): await nft_preview.import_preview("https://t.me/nft/Gift-1")
    assert len(seen) == 1
    mode = "large"
    with pytest.raises(ValueError, match="большое"): await nft_preview.import_preview("https://t.me/nft/Gift-1")


async def test_unknown_post_must_be_resolved_before_cancellation(client, db, staff, giveaway):
    admin, moderator, _ = staff
    giveaway.post_status, giveaway.post_chat_id = "unknown", -100987
    await db.commit()
    path = f"/api/admin/giveaways/{giveaway.id}"
    headers = _bearer(admin, role="admin")
    assert (await client.post(path + "/cancel", headers=headers)).status_code == 409
    assert (await client.post(path + "/post-resolution", headers=_bearer(moderator, role="moderator"), json={"message_id":5})).status_code == 403
    assert (await client.post(path + "/post-resolution", headers=headers, json={"message_id":5})).status_code == 200
    assert (await client.post(path + "/cancel", headers=headers)).status_code == 200
    status = await client.get('/api/admin/giveaways/cleanup-status', headers=headers)
    assert status.json() == {"pending":1, "retrying":0}


@pytest.mark.parametrize("code,expected", [(None, "unknown"), (500, "unknown"), (429, "failed")])
async def test_only_definitive_send_failures_are_retryable(db, giveaway, monkeypatch, code, expected):
    monkeypatch.setattr(life.settings, "VITE_BOT_USERNAME", "Example_bot")
    giveaway.post_status, giveaway.post_chat_id = "queued", -100987
    await db.commit()
    send = AsyncMock(side_effect=TelegramApiError("sendMessage", "response unavailable", code))
    monkeypatch.setattr(life, "_call", send)
    await life.dispatch_post(factory(db))
    assert giveaway.post_status == expected
    assert not await life.dispatch_post(factory(db))
    assert send.await_count == 1
