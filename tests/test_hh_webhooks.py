import pytest
import httpx
from sqlalchemy import insert

from app.api import hh_webhooks
from app.db.db import get_session
from app.db import models
from app.db.token_store import DbTokenStore


@pytest.mark.asyncio
async def test_ensure_hh_webhook_uses_first_owner(in_memory_db, monkeypatch):
    # Insert tokens for two employers
    async with get_session() as s:
        await s.execute(
            insert(models.Token).values(
                id=1,
                service="hh",
                owner_id="1",
                access_token="tok1",
                refresh_token="r1",
                expires_at=0,
            )
        )
        await s.execute(
            insert(models.Token).values(
                id=2,
                service="hh",
                owner_id="2",
                access_token="tok2",
                refresh_token="r2",
                expires_at=0,
            )
        )
        await s.commit()

    async def fake_list_owners(service: str):
        return ["2", "1"]

    monkeypatch.setattr(DbTokenStore, "list_owners", staticmethod(fake_list_owners))
    monkeypatch.setattr(hh_webhooks, "_target_url", lambda: "http://example.com")

    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await hh_webhooks.ensure_hh_webhook(client)

    assert captured, "no requests were made"
    assert captured[0].headers.get("Authorization") == "Bearer tok2"


@pytest.mark.asyncio
async def test_ensure_hh_webhook_handles_get_404(in_memory_db, monkeypatch, caplog):
    # Insert token for a single employer
    async with get_session() as s:
        await s.execute(
            insert(models.Token).values(
                id=1,
                service="hh",
                owner_id="1",
                access_token="tok",
                refresh_token="r",
                expires_at=0,
            )
        )
        await s.commit()

    monkeypatch.setattr(hh_webhooks, "_target_url", lambda: "http://example.com")

    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.method == "GET":
            return httpx.Response(404, json={"errors": [{"type": "not_found"}]})
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with caplog.at_level("WARNING"):
            await hh_webhooks.ensure_hh_webhook(client)

    assert len(captured) == 1
    assert captured[0].method == "GET"
    assert "HH webhook: 404" in caplog.text
