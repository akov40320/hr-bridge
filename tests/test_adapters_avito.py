import json
import pytest
import httpx

from app.adapters import avito


@pytest.mark.asyncio
async def test_avito_send_message(monkeypatch, token_mock):
    async def fake_with_retry(coro, attempts, is_retryable):
        return await coro()

    monkeypatch.setattr(avito, "with_retry", fake_with_retry)
    token = token_mock

    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content.decode())
        assert request.headers["Authorization"] == f"Bearer {token}"
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await avito.send_message("neg1", "hi", "owner1", client)

    assert captured["url"].endswith("/messenger/v1/accounts/me/chats/neg1/messages")
    assert captured["json"] == {"message": {"text": "hi"}}


@pytest.mark.asyncio
async def test_avito_send_message_error(monkeypatch, token_mock):
    async def fake_with_retry(coro, attempts, is_retryable):
        return await coro()

    monkeypatch.setattr(avito, "with_retry", fake_with_retry)

    def handler(request):
        return httpx.Response(500, json={"error": "fail"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(avito.AvitoError):
            await avito.send_message("neg1", "hi", None, client)


@pytest.mark.asyncio
async def test_avito_mark_read(monkeypatch, token_mock):
    async def fake_with_retry(coro, attempts, is_retryable):
        return await coro()

    monkeypatch.setattr(avito, "with_retry", fake_with_retry)
    token = token_mock

    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        assert request.headers["Authorization"] == f"Bearer {token}"
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await avito.mark_read("neg1", "owner1", client)

    assert captured["url"].endswith("/messenger/v1/accounts/me/chats/neg1/read")
