import pytest
from app.services.worker import mirror as worker_mirror


@pytest.mark.asyncio
async def test_tg_to_amo_sets_conversation(monkeypatch):
    conv_id = "lead:21985897"

    class DummyAmo:
        async def get_lead_with_contacts(self, lead_id):
            return {"_embedded": {"contacts": [{"id": 21985897}]}}

    class DummyAmoClient:
        @staticmethod
        async def create(client):
            return DummyAmo()

    async def fake_ensure_chat_created(**kwargs):
        return conv_id

    async def fake_send_text_from_client(**kwargs):
        return conv_id

    called = {}

    async def fake_set_conversation(user_id, bot_kind, cid):
        called["args"] = (user_id, bot_kind, cid)

    async def fake_check_and_store(key):
        return True

    async def fake_with_retry(func, attempts, is_retryable):
        return await func()

    monkeypatch.setattr(worker_mirror, "AmoClient", DummyAmoClient)
    monkeypatch.setattr(worker_mirror, "ensure_chat_created", fake_ensure_chat_created)
    monkeypatch.setattr(worker_mirror, "send_text_from_client", fake_send_text_from_client)
    monkeypatch.setattr(worker_mirror, "set_conversation", fake_set_conversation)
    monkeypatch.setattr(worker_mirror, "check_and_store", fake_check_and_store)
    monkeypatch.setattr(worker_mirror, "with_retry", fake_with_retry)

    payload = {
        "lead_id": "123",
        "text": "hi",
        "tg_user_id": "10",
        "tg_user_name": "u",
        "bot_kind": "master",
    }

    await worker_mirror.handle_mirror_tg_to_amo(payload)

    assert called["args"] == (10, "master", conv_id)
