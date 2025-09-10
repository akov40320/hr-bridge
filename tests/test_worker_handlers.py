import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app.services import worker_rmq
from app.services.worker import hh as worker_hh
from app.services.worker import avito as worker_avito
from app.services.worker import mirror as worker_mirror
from app.services.worker import amo as worker_amo


@pytest.mark.parametrize(
    "key,func",
    [
        (("hh", "send_message"), worker_hh.handle_hh_send_message),
        (("avito", "send_message"), worker_avito.handle_avito_send_message),
        (("mirror", "amo_to_tg"), worker_mirror.handle_mirror_amo_to_tg),
        (("amo", "amo_update_status"), worker_amo.handle_amo_update_status),
    ],
)
def test_handler_mapping(key, func):
    assert worker_rmq.HANDLERS[key] is func


@pytest.mark.asyncio
async def test_hh_send_message_idempotent(monkeypatch, in_memory_db):
    calls = []

    async def fake_send_message(response_id, text, employer_id, client):
        calls.append((response_id, text))

    monkeypatch.setattr(worker_hh.hh_adapt, "send_message", fake_send_message)
    monkeypatch.setattr(worker_hh, "get_http_client", lambda: object())

    payload = {"negotiation_id": "nid", "text": "hi", "msg_key": "k1"}
    await worker_hh.handle_hh_send_message(payload)
    await worker_hh.handle_hh_send_message(payload)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_hh_set_state_idempotent(monkeypatch, in_memory_db):
    calls = []

    async def fake_set_state(response_id, target_state, employer_id, client):
        calls.append((response_id, target_state))

    monkeypatch.setattr(worker_hh.hh_adapt, "set_employer_state", fake_set_state)
    monkeypatch.setattr(worker_hh, "get_http_client", lambda: object())

    payload = {"negotiation_id": "nid", "action_id": "state", "msg_key": "k2"}
    await worker_hh.handle_hh_set_state(payload)
    await worker_hh.handle_hh_set_state(payload)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_avito_send_message_idempotent(monkeypatch, in_memory_db):
    calls = []

    async def fake_send_message(external_id, text, owner_id=None, client=None):
        calls.append((external_id, text))

    async def fake_perform_request(func, *args, **kwargs):
        return await func(*args, **kwargs)

    monkeypatch.setattr(worker_avito.avito_adapt, "send_message", fake_send_message)
    monkeypatch.setattr(worker_avito, "perform_request", fake_perform_request)

    payload = {"external_id": "e1", "text": "t", "msg_key": "k3"}
    await worker_avito.handle_avito_send_message(payload)
    await worker_avito.handle_avito_send_message(payload)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_amo_create_lead_idempotent(monkeypatch, in_memory_db):
    calls = []

    class DummyClient:
        async def create_leads(self, body):
            calls.append(body)

    async def fake_create(cls, http_client):
        return DummyClient()

    monkeypatch.setattr(worker_amo.AmoClient, "create", classmethod(fake_create))
    monkeypatch.setattr(worker_amo, "get_http_client", lambda: object())

    payload = {"lead_body": [{"name": "n"}], "msg_key": "k4"}
    await worker_amo.handle_amo_create_lead(payload)
    await worker_amo.handle_amo_create_lead(payload)
    assert len(calls) == 1
