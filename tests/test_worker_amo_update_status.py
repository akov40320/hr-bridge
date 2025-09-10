import os
import sys
import types
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.worker import amo as worker_amo


@pytest.mark.asyncio
async def test_handle_amo_update_status(monkeypatch):
    captured = {}

    class DummyAmo:
        async def update_status(self, lead_id, status_id):
            captured['lead_id'] = lead_id
            captured['status_id'] = status_id

    async def fake_create(cls, http_client):
        return DummyAmo()

    async def fake_get_last_transition(lead_id):
        captured['checked'] = lead_id
        return None

    async def fake_set_last_transition(lead_id, status_id, ts):
        captured['saved'] = (lead_id, status_id, ts)

    monkeypatch.setattr(worker_amo.AmoClient, 'create', classmethod(fake_create))
    monkeypatch.setattr(worker_amo, 'get_http_client', lambda: None)
    monkeypatch.setattr(worker_amo, 'get_last_transition', fake_get_last_transition)
    monkeypatch.setattr(worker_amo, 'set_last_transition', fake_set_last_transition)

    await worker_amo.handle_amo_update_status({'lead_id': '1', 'status_id': '2', 'ts': 100})

    assert captured['lead_id'] == 1
    assert captured['status_id'] == 2
    assert captured['checked'] == 1
    assert captured['saved'] == (1, 2, 100)


@pytest.mark.asyncio
async def test_handle_amo_update_status_stale(monkeypatch):
    called = {}

    class DummyAmo:
        async def update_status(self, lead_id, status_id):
            called['updated'] = True

    async def fake_create(cls, http_client):
        called['created'] = True
        return DummyAmo()

    async def fake_get_last_transition(lead_id):
        return types.SimpleNamespace(ts=200)

    async def fake_set_last_transition(lead_id, status_id, ts):
        called['saved'] = True

    monkeypatch.setattr(worker_amo.AmoClient, 'create', classmethod(fake_create))
    monkeypatch.setattr(worker_amo, 'get_http_client', lambda: None)
    monkeypatch.setattr(worker_amo, 'get_last_transition', fake_get_last_transition)
    monkeypatch.setattr(worker_amo, 'set_last_transition', fake_set_last_transition)

    await worker_amo.handle_amo_update_status({'lead_id': '1', 'status_id': '2', 'ts': 100})

    assert called == {}
