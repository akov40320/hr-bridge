import json
import hmac
import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.store_chat import upsert_tg_link, set_conversation
from app.api import api_amochats
from app.api.api_amochats import resolve_links

@pytest.mark.asyncio
async def test_resolve_links_uses_client_conv_id(in_memory_db):
    user_id = 123
    bot_kind = "master"
    lead_id = 20832209
    conv_client_id = "contact:21982943"
    chat_id = "97ddeb13-db49-4988-8160-5db861425fc2"

    await upsert_tg_link(user_id, bot_kind, lead_id)
    await set_conversation(user_id, bot_kind, conv_client_id)

    links = await resolve_links(chat_id, conv_client_id, None, {}, {})
    assert len(links) == 1
    assert links[0].user_id == user_id
    assert links[0].conversation_id == conv_client_id


@pytest.fixture
def amochats_client(monkeypatch):
    app = FastAPI()
    
    class DummySettings:
        AMO_CHATS_SECRET = "secret"

    async def fake_check_and_store(key):
        return True

    async def fake_resolve_links(*args, **kwargs):
        return []

    monkeypatch.setattr(api_amochats, "check_and_store", fake_check_and_store)
    monkeypatch.setattr(api_amochats, "resolve_links", fake_resolve_links)

    app.dependency_overrides[api_amochats.get_settings] = lambda: DummySettings()
    app.include_router(api_amochats.router_amo_chats)
    return TestClient(app)


def _payload() -> dict:
    return {
        "message": {
            "conversation": {"id": "conv1"},
            "sender": {},
            "receiver": {},
            "message": {"text": "hi"},
        }
    }


def test_webhook_valid_signature(amochats_client, queue_mock):
    body = json.dumps(_payload()).encode("utf-8")
    sig = hmac.new(b"secret", body, hashlib.sha1).hexdigest()
    resp = amochats_client.post(
        "/webhooks/amo-chats/in/test", content=body, headers={"X-Signature": sig}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

# TODO: подпись
# def test_webhook_invalid_signature(amochats_client, queue_mock):
#     body = json.dumps(_payload()).encode("utf-8")
#     resp = amochats_client.post(
#         "/webhooks/amo-chats/in/test", content=body, headers={"X-Signature": "bad"}
#     )
#     assert resp.status_code == 401
