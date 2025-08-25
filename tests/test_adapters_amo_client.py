import os
import sys
import json
import pytest
import httpx

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.adapters.amo_client import AmoClient
import app.adapters.amo_client as amo_client_module


class DummyStore:
    async def save(self, data):  # pragma: no cover - not used but required
        pass


@pytest.mark.asyncio
async def test_update_status(monkeypatch):
    class DummySettings:
        AMO_BASE_URL = "https://example.com"

    monkeypatch.setattr(amo_client_module, "get_settings", lambda: DummySettings())

    tokens = {"access_token": "acc", "refresh_token": "ref", "expires_at": 10**10}
    captured = {}

    def handler(request):
        captured["method"] = request.method
        captured["url"] = request.url
        captured["json"] = json.loads(request.content.decode())
        assert request.headers["Authorization"] == "Bearer acc"
        assert request.headers["Accept"] == "application/json"
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        amo = AmoClient(tokens, DummyStore(), client)
        await amo.update_status(123, 456)

    assert captured["method"] == "PATCH"
    assert captured["url"].path == "/api/v4/leads"
    assert captured["json"] == [{"id": 123, "status_id": 456}]
