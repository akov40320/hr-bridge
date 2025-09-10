import json
import pytest
import httpx
from sqlalchemy import insert
from pydantic import SecretStr

from app.api import hh_webhooks
from app.db.db import get_session
from app.db import models
from app.db.token_store import DbTokenStore


@pytest.fixture(autouse=True)
def patch_ensure_fresh_access(monkeypatch):
    async def fake_ensure(*, config, **kwargs):
        return f"tok{config.owner_id}"

    monkeypatch.setattr(hh_webhooks, "ensure_fresh_access", fake_ensure)


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


def _set_events(monkeypatch, value: str):
    class Dummy:
        HH_WEBHOOK_EVENTS = value
        HH_TOKEN_URL = "https://example.com/token"
        HH_CLIENT_ID = "id"
        HH_CLIENT_SECRET = SecretStr("secret")
        HH_REDIRECT_URI = "http://example.com/cb"

    monkeypatch.setattr(hh_webhooks, "get_settings", lambda: Dummy())


def test_events_filtered(monkeypatch, caplog):
    _set_events(monkeypatch, "negotiation_created,invalid")

    with caplog.at_level("WARNING"):
        actions = hh_webhooks._actions()

    assert actions == [
        {"type": "NEW_NEGOTIATION_VACANCY", "settings": {"vacancies_only_mine": False}}
    ]
    assert "неподдерживаемые события" in caplog.text


@pytest.mark.asyncio
async def test_ensure_skips_when_no_valid_events(in_memory_db, monkeypatch):
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
        await s.commit()

    async def fake_list_owners(service: str):
        return ["1"]

    monkeypatch.setattr(DbTokenStore, "list_owners", staticmethod(fake_list_owners))
    monkeypatch.setattr(hh_webhooks, "_target_url", lambda: "http://example.com")
    _set_events(monkeypatch, "invalid")

    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await hh_webhooks.ensure_hh_webhook(client)

    assert captured == []


@pytest.mark.asyncio
async def test_ensure_posts_only_valid_events(in_memory_db, monkeypatch):
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
        await s.commit()

    async def fake_list_owners(service: str):
        return ["1"]

    monkeypatch.setattr(DbTokenStore, "list_owners", staticmethod(fake_list_owners))
    monkeypatch.setattr(hh_webhooks, "_target_url", lambda: "http://example.com")
    _set_events(monkeypatch, "negotiation_created,invalid")

    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await hh_webhooks.ensure_hh_webhook(client)

    assert len(captured) == 2
    assert json.loads(captured[1].content)["actions"] == [
        {"type": "NEW_NEGOTIATION_VACANCY", "settings": {"vacancies_only_mine": False}}
    ]
