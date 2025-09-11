import pytest

from app.services.worker import hh as worker_hh


@pytest.mark.asyncio
async def test_handle_hh_set_state_external_id(monkeypatch):
    called = {}

    async def fake_set_employer_state(response_id, target_state, employer_id, client):
        called['args'] = (response_id, target_state, employer_id)
        called['client'] = client

    monkeypatch.setattr(worker_hh.hh_adapt, 'set_employer_state', fake_set_employer_state)
    monkeypatch.setattr(worker_hh, 'get_http_client', lambda: 'client')

    payload = {
        'external_id': 'nid',
        'action_id': 'interview',
        'owner_id': 'owner',
    }

    await worker_hh.handle_hh_set_state(payload)

    assert called['args'] == ('nid', 'interview', 'owner')
    assert called['client'] == 'client'


@pytest.mark.asyncio
async def test_handle_hh_send_message_external_id(monkeypatch):
    called = {}

    async def fake_send_message(response_id, text, employer_id, client):
        called['args'] = (response_id, text, employer_id)
        called['client'] = client

    monkeypatch.setattr(worker_hh.hh_adapt, 'send_message', fake_send_message)
    monkeypatch.setattr(worker_hh, 'get_http_client', lambda: 'client')

    payload = {
        'external_id': 'nid',
        'text': 'hello',
        'owner_id': 'owner',
    }

    await worker_hh.handle_hh_send_message(payload)

    assert called['args'] == ('nid', 'hello', 'owner')
    assert called['client'] == 'client'
