import asyncio

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from pydantic import SecretStr

from app.core.guards import require_admin
from app.db.db import get_session
from app.db import models
from sqlalchemy import insert


@pytest.fixture
def app(monkeypatch):
    """Application exposing admin token endpoints."""

    from app.api import admin as admin_module

    class Dummy:
        ADMIN_TOKEN = SecretStr("adm")
        HH_TOKEN_URL = "https://example.com/hh/token"
        HH_CLIENT_ID = "id"
        HH_CLIENT_SECRET = SecretStr("secret")
        HH_REDIRECT_URI = "http://example.com/hh"
        AVITO_TOKEN_URL = "https://example.com/avito/token"
        AVITO_CLIENT_ID = "aid"
        AVITO_CLIENT_SECRET = SecretStr("asecret")
        AVITO_REDIRECT_URI = "http://example.com/avito"
        AMO_BASE_URL = "https://amo.example.com"
        AMO_CLIENT_ID = "amoid"
        AMO_CLIENT_SECRET = SecretStr("amosecret")
        AMO_REDIRECT_URI = "http://example.com/amo"

    monkeypatch.setattr("app.core.guards.get_settings", lambda: Dummy())
    monkeypatch.setattr(admin_module, "get_settings", lambda: Dummy())

    app = FastAPI()
    admin_router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
    admin_router.include_router(admin_module.admin)
    app.include_router(admin_router)
    return app


@pytest.mark.asyncio
async def test_tokens_owners_returns_all(app, in_memory_db):
    async with get_session() as s:
        await s.execute(
            insert(models.Token).values(
                id=1,
                service="hh",
                owner_id="1",
                access_token="a",
                refresh_token="r",
                expires_at=10,
            )
        )
        await s.execute(
            insert(models.Token).values(
                id=2,
                service="avito",
                owner_id="2",
                access_token="a2",
                refresh_token="r2",
                expires_at=20,
            )
        )
        await s.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/admin/tokens/owners", headers={"X-Admin-Token": "adm"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    services = {(it["service"], it["owner_id"]) for it in data["items"]}
    assert services == {("hh", "1"), ("avito", "2")}


@pytest.mark.asyncio
async def test_tokens_refresh_calls_ensure(app, in_memory_db, monkeypatch):
    async with get_session() as s:
        await s.execute(
            insert(models.Token).values(
                id=1,
                service="hh",
                owner_id="1",
                access_token="a1",
                refresh_token="r1",
                expires_at=0,
            )
        )
        await s.execute(
            insert(models.Token).values(
                id=2,
                service="hh",
                owner_id="2",
                access_token="a2",
                refresh_token="r2",
                expires_at=0,
            )
        )
        await s.commit()

    called = []

    async def fake_ensure_fresh_access(*, config, **kwargs):
        called.append(config.owner_id)
        return "tok"

    from app.api import admin as admin_module

    monkeypatch.setattr(admin_module, "ensure_fresh_access", fake_ensure_fresh_access)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/admin/tokens/refresh", params={"platform": "hh"}, headers={"X-Admin-Token": "adm"}
        )
    assert r.status_code == 200
    assert set(called) == {"1", "2"}


@pytest.mark.asyncio
async def test_tokens_ensure_calls_bootstrap(app, monkeypatch):
    called = False

    async def fake_ensure_tokens():
        nonlocal called
        called = True

    from app.api import admin as admin_module

    monkeypatch.setattr(admin_module, "ensure_tokens", fake_ensure_tokens)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/admin/tokens/ensure", headers={"X-Admin-Token": "adm"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert called is True

