import os
import sys
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

    monkeypatch.setattr(worker_amo.AmoClient, 'create', classmethod(fake_create))
    monkeypatch.setattr(worker_amo, 'get_http_client', lambda: None)

    await worker_amo.handle_amo_update_status({'lead_id': '1', 'status_id': '2'})

    assert captured == {'lead_id': 1, 'status_id': 2}
