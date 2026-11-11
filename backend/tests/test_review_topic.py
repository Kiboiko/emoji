import httpx
import pytest
from pydantic import ValidationError

from config import Settings
from services import telegram_service


@pytest.mark.asyncio
@pytest.mark.parametrize('thread_id', [0, 16])
async def test_review_destination_preserves_topic_and_escaped_text(monkeypatch, thread_id):
    monkeypatch.setattr(telegram_service.settings, 'REVIEWS_CHANNEL_ID', '@SafeDeal_Chat')
    monkeypatch.setattr(telegram_service.settings, 'REVIEWS_THREAD_ID', thread_id)
    service = telegram_service.TelegramService()
    posted = []

    class Client:
        async def __aenter__(self):return self
        async def __aexit__(self, *args):pass
        async def post(self, url, *, json):
            posted.append(json)
            return httpx.Response(200, json={'ok': True, 'result': {'message_id': 42}},
                                  request=httpx.Request('POST', 'https://telegram.invalid/sendMessage'))

    monkeypatch.setattr(telegram_service.httpx, 'AsyncClient', Client)
    result = await service.publish_review_to_channel(
        product_name='Game <Deluxe>', price_usdt=2, review_text='Great <3 & fast', rating=5,
    )
    assert result == 42
    assert len(posted) == 1
    assert posted[0]['chat_id'] == '@SafeDeal_Chat'
    assert posted[0]['parse_mode'] == 'HTML'
    assert 'Great &lt;3 &amp; fast' in posted[0]['text']
    if thread_id:
        assert posted[0]['message_thread_id'] == 16
    else:
        assert 'message_thread_id' not in posted[0]


def test_review_topic_rejects_negative_id():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, REVIEWS_THREAD_ID=-1)
