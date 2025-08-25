import pytest

from app.services.worker import hh as worker_hh
from app.adapters import hh as hh_adapt


@pytest.mark.asyncio
async def test_send_message_topic_not_found(monkeypatch):
    async def fake_send_message(*args, **kwargs):
        raise hh_adapt.HHError("topic_not_found")

    monkeypatch.setattr(hh_adapt, "send_message", fake_send_message)
    monkeypatch.setattr(worker_hh, "get_http_client", lambda: None)

    payload = {"negotiation_id": "nid", "text": "hello"}
    await worker_hh.handle_hh_send_message(payload)


@pytest.mark.asyncio
async def test_set_state_topic_not_found(monkeypatch):
    async def fake_set_state(*args, **kwargs):
        raise hh_adapt.HHError("topic_not_found")

    monkeypatch.setattr(hh_adapt, "set_employer_state", fake_set_state)
    monkeypatch.setattr(worker_hh, "get_http_client", lambda: None)

    payload = {"negotiation_id": "nid", "action_id": "phone_interview"}
    await worker_hh.handle_hh_set_state(payload)
