import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import admin as admin_module
from app.api import build_routers
from app.core.config import get_settings


def _build_client(monkeypatch) -> TestClient:
    settings = get_settings()
    monkeypatch.setattr(settings, "ADMIN_TOKEN", SecretStr("secret"))
    app = FastAPI()
    _, admin_router = build_routers()
    app.include_router(admin_router)
    return TestClient(app)


def test_admin_ensure_hh_webhook(monkeypatch):
    called = []

    async def fake_ensure(client):
        called.append(client)

    monkeypatch.setattr(admin_module, "ensure_hh_webhook", fake_ensure)
    client = _build_client(monkeypatch)
    r = client.post("/admin/hh-webhook/ensure", headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert len(called) == 1
    assert isinstance(called[0], httpx.AsyncClient)


def test_admin_ensure_avito_webhook(monkeypatch):
    called = []

    async def fake_ensure(client):
        called.append(client)

    monkeypatch.setattr(admin_module, "ensure_avito_webhooks", fake_ensure)
    client = _build_client(monkeypatch)
    r = client.post("/admin/avito-webhook/ensure", headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert len(called) == 1
    assert isinstance(called[0], httpx.AsyncClient)
