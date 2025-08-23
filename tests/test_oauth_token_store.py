import time
import pytest
import httpx

from app.api import oauth2
from app.db.token_store import DbTokenStore
from app.db.db import get_session
from app.db import models
from sqlalchemy import insert


@pytest.mark.asyncio
async def test_refresh_tokens_saves_to_db(in_memory_db):
    async with get_session() as s:
        await s.execute(
            insert(models.Token).values(
                id=1,
                service="svc",
                owner_id=None,
                access_token="old",
                refresh_token="oldr",
                expires_at=0,
            )
        )
        await s.commit()

    def handler(request):
        assert request.url == httpx.URL("https://example.com/token")
        return httpx.Response(
            200,
            json={
                "access_token": "new_token",
                "refresh_token": "new_refresh",
                "expires_in": 100,
                "server_time": 1000,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        data = await oauth2.refresh_tokens(
            service="svc",
            token_url="https://example.com/token",
            client_id="id",
            client_secret="secret",
            refresh_token="old_refresh",
            http_client=client,
        )

    assert data["access_token"] == "new_token"
    store = DbTokenStore("svc")
    loaded = await store.load()
    assert loaded["refresh_token"] == "new_refresh"


@pytest.mark.asyncio
async def test_ensure_fresh_access_refreshes_when_expired(in_memory_db):
    store = DbTokenStore("svc")
    now = int(time.time())
    async with get_session() as s:
        await s.execute(
            insert(models.Token).values(
                id=1,
                service="svc",
                owner_id=None,
                access_token="old",
                refresh_token="r1",
                expires_at=now - 10,
            )
        )
        await s.commit()

    def handler(request):
        return httpx.Response(
            200,
            json={
                "access_token": "new",
                "refresh_token": "r2",
                "expires_in": 200,
                "server_time": now,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        token = await oauth2.ensure_fresh_access(
            service="svc",
            token_url="https://example.com/token",
            client_id="id",
            client_secret="secret",
            owner_id=None,
            http_client=client,
        )

    assert token == "new"
    loaded = await store.load()
    assert loaded["access_token"] == "new" and loaded["refresh_token"] == "r2"


@pytest.mark.asyncio
async def test_ensure_fresh_access_uses_cached_token(in_memory_db, monkeypatch):
    store = DbTokenStore("svc")
    now = int(time.time())
    async with get_session() as s:
        await s.execute(
            insert(models.Token).values(
                id=1,
                service="svc",
                owner_id=None,
                access_token="cached",
                refresh_token="r1",
                expires_at=now + 1000,
            )
        )
        await s.commit()

    called = False

    async def fake_refresh_tokens(**kwargs):
        nonlocal called
        called = True
        return {"access_token": "new", "refresh_token": "r2", "expires_at": now + 1000}

    monkeypatch.setattr(oauth2, "refresh_tokens", fake_refresh_tokens)

    token = await oauth2.ensure_fresh_access(
        service="svc",
        token_url="https://example.com/token",
        client_id="id",
        client_secret="secret",
    )

    assert token == "cached"
    assert called is False
