import pytest

from app.services import common_request


@pytest.mark.asyncio
async def test_perform_request_uses_shared_client(monkeypatch):
    called = {}

    async def dummy_adapter(arg1, client, arg2=None):
        called['client'] = client
        called['args'] = (arg1, arg2)
        return 'ok'

    sentinel_client = object()
    monkeypatch.setattr(common_request, 'get_http_client', lambda: sentinel_client)

    result = await common_request.perform_request(dummy_adapter, 'a', arg2='b')
    assert result == 'ok'
    assert called['client'] is sentinel_client
    assert called['args'] == ('a', 'b')


@pytest.mark.asyncio
async def test_perform_request_custom_client(monkeypatch):
    called = {}

    async def dummy_adapter(client):
        called['client'] = client
        return 'done'

    def fake_get_http_client():
        raise AssertionError('get_http_client should not be called')

    monkeypatch.setattr(common_request, 'get_http_client', fake_get_http_client)
    explicit_client = object()

    result = await common_request.perform_request(dummy_adapter, client=explicit_client)
    assert result == 'done'
    assert called['client'] is explicit_client
