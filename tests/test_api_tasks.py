import pytest
from app.api import tasks as api_tasks

@pytest.mark.asyncio
async def test_handle_task_hh_send_message(monkeypatch):
    called = {}

    async def fake_send_message(response_id, text, employer_id, client):
        called['args'] = (response_id, text, employer_id)
        called['client'] = client

    monkeypatch.setattr(api_tasks.hh_adapt, 'send_message', fake_send_message)
    monkeypatch.setattr(api_tasks, 'get_http_client', lambda: 'client')

    payload = {
        'platform': 'hh',
        'action': 'send_message',
        'negotiation_id': 'nid',
        'text': 'hi',
        'owner_id': 'owner',
    }

    await api_tasks.handle_task(payload)

    assert called['args'] == ('nid', 'hi', 'owner')
    assert called['client'] == 'client'
