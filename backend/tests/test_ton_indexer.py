"""Indexer outages must retry safely and never turn into missing payments."""
import traceback
import httpx
import pytest

from config import settings
from services import ton_service


@pytest.fixture
def indexer(monkeypatch):
    actual_client = httpx.AsyncClient
    monkeypatch.setattr(settings, 'TON_API_KEY', 'private-indexer-test-key')
    monkeypatch.setattr(ton_service, 'require_receiving_address', lambda: 'EQFixture')
    async def no_delay(_): pass
    monkeypatch.setattr(ton_service.asyncio, 'sleep', no_delay)
    def install(handler):
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: actual_client(transport=httpx.MockTransport(handler), **kwargs))
    return install


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [429, 500, 502, 503, 504])
async def test_transient_error_retries_and_returns_real_transaction(indexer, status):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.headers['X-API-Key'] == 'private-indexer-test-key'
        assert 'api_key' not in request.url.params
        if len(requests) == 1: return httpx.Response(status)
        return httpx.Response(200, json={'ok':True,'result':[{
            'transaction_id':{'hash':'verified-chain-hash','lt':'123'},'utime':100,
            'in_msg':{'source':'EQBuyer','value':'1000000000','message':'PROMO-fixture'},
        }]})
    indexer(respond)
    transactions = await ton_service.fetch_incoming_transactions()
    assert len(requests) == 2
    assert len(transactions) == 1
    assert transactions[0].value_nano == 1_000_000_000
    assert transactions[0].comment == 'PROMO-fixture'


@pytest.mark.asyncio
async def test_exhausted_outage_is_an_error_with_no_key_in_traceback(indexer):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(500)
    indexer(respond)
    with pytest.raises(ton_service.TonTemporaryError) as error:
        await ton_service.fetch_incoming_transactions()
    assert len(requests) == 3
    assert 'private-indexer-test-key' not in ''.join(traceback.format_exception(error.value))


@pytest.mark.asyncio
async def test_invalid_credentials_fail_immediately(indexer):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(401)
    indexer(respond)
    with pytest.raises(ton_service.TonError) as error:
        await ton_service.fetch_incoming_transactions()
    assert len(requests) == 1
    assert not isinstance(error.value, ton_service.TonTemporaryError)


@pytest.mark.asyncio
async def test_connection_failure_retries(indexer):
    requests = []
    def respond(request):
        requests.append(request)
        if len(requests)==1: raise httpx.ConnectError('network unavailable',request=request)
        return httpx.Response(200,json={'ok':True,'result':[]})
    indexer(respond)
    assert await ton_service.fetch_incoming_transactions() == []
    assert len(requests)==2
