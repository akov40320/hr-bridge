import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from pydantic import SecretStr

from app.core.guards import require_admin


class DummySettings:
    ADMIN_TOKEN = SecretStr("adm")
    AMO_PIPELINE_ID_MASTER = 1
    AMO_PIPELINE_ID_OPERATOR = 2


@pytest.fixture
def app(monkeypatch):
    from app.api import admin as admin_module

    settings = DummySettings()
    monkeypatch.setattr("app.core.guards.get_settings", lambda: settings)
    monkeypatch.setattr(admin_module, "get_settings", lambda: settings)

    app = FastAPI()
    admin_router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
    admin_router.include_router(admin_module.admin)
    app.include_router(admin_router)
    return app


@pytest.mark.asyncio
async def test_dlq_requeue_calls_queue_client(app, monkeypatch):
    from app.api import admin as admin_module

    class DummyQueue:
        def __init__(self):
            self.called = None

        async def requeue_dlq(self, n):
            self.called = n
            return 3

    q = DummyQueue()
    monkeypatch.setattr(admin_module, "rabbitmq", q)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/admin/dlq/requeue", params={"n": 5}, headers={"X-Admin-Token": "adm"}
        )
    assert r.status_code == 200
    assert q.called == 5
    assert r.json()["requeued"] == 3


@pytest.mark.asyncio
async def test_replay_lead_skip_dedup(app, monkeypatch):
    from app.api import admin as admin_module

    async def fake_process(platform, raw, http_client, parser, *, skip_dedup=False):
        return {
            "platform": platform,
            "raw": raw.decode(),
            "skip": skip_dedup,
            "parsed": parser(b"{}"),
        }

    def fake_parse(raw):
        return {"raw": raw.decode()}

    monkeypatch.setattr(admin_module, "process_job_board_webhook", fake_process)
    monkeypatch.setattr(admin_module, "parse_hh_payload", fake_parse)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/admin/replay/lead", params={"platform": "hh"}, content=b"{}", headers={"X-Admin-Token": "adm"}
        )
    data = r.json()
    assert data["platform"] == "hh"
    assert data["skip"] is True


@pytest.mark.asyncio
async def test_replay_survey_invite(app, monkeypatch):
    from app.api import admin as admin_module

    async def fake_find_link(lead_id):
        return {"platform": "hh", "owner_id": "o", "vacancy_id": "v", "external_id": "nid"}

    class DummyAmo:
        async def get_lead(self, lead_id):
            return {"pipeline_id": 1}

    async def fake_create(client):
        return DummyAmo()

    called = {}

    async def fake_send_invite(payload, lead_id):
        called["payload"] = payload
        called["lead_id"] = lead_id

    monkeypatch.setattr(admin_module, "find_link", fake_find_link)
    monkeypatch.setattr(admin_module.AmoClient, "create", classmethod(lambda cls, client: fake_create(client)))
    monkeypatch.setattr(admin_module, "send_invite", fake_send_invite)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/admin/replay/survey-invite", params={"lead_id": 42}, headers={"X-Admin-Token": "adm"}
        )
    assert r.status_code == 200
    assert called["lead_id"] == 42
    assert called["payload"].applicant.id == "nid"
    assert called["payload"].kind == "master"


@pytest.mark.asyncio
async def test_status_sync_lead(app, monkeypatch):
    from app.api import admin as admin_module

    async def fake_find_link(lead_id):
        return {"platform": "hh", "owner_id": "o", "external_id": "nid"}

    class DummyAmo:
        async def get_lead(self, lead_id):
            return {"status_id": 10}

    async def fake_create(client):
        return DummyAmo()

    called = {}

    async def fake_sync(lead_id, status_id, link, http_client):
        called.update(lead_id=lead_id, status_id=status_id, link=link)

    monkeypatch.setattr(admin_module, "find_link", fake_find_link)
    monkeypatch.setattr(admin_module.AmoClient, "create", classmethod(lambda cls, client: fake_create(client)))
    monkeypatch.setattr(admin_module, "sync_hh_status", fake_sync)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/admin/status-sync/lead", params={"lead_id": 5}, headers={"X-Admin-Token": "adm"}
        )
    assert r.status_code == 200
    assert called["lead_id"] == 5
    assert called["status_id"] == 10
    assert called["link"]["external_id"] == "nid"
