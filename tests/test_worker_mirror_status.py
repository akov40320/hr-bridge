import pytest

from app.services.worker import mirror as worker_mirror


@pytest.mark.asyncio
async def test_status_update_on_chat_creation(monkeypatch, queue_mock):
    async def fake_ensure_chat_created(**kwargs):
        return "lead:123"

    keys = set()

    async def fake_check_and_store(key):
        if key in keys:
            return False
        keys.add(key)
        return True

    async def fake_send_text_from_manager(**kwargs):
        return None

    async def fake_with_retry(func, attempts, is_retryable):
        return await func()

    class DummyAmo:
        async def get_lead_with_contacts(self, lead_id):
            return {}

    class DummyAmoClient:
        @staticmethod
        async def create(client):
            return DummyAmo()

    monkeypatch.setattr(worker_mirror, "ensure_chat_created", fake_ensure_chat_created)
    monkeypatch.setattr(worker_mirror, "check_and_store", fake_check_and_store)
    monkeypatch.setattr(worker_mirror, "send_text_from_manager", fake_send_text_from_manager)
    monkeypatch.setattr(worker_mirror, "with_retry", fake_with_retry)
    monkeypatch.setattr(worker_mirror, "AmoClient", DummyAmoClient)

    payload = {
        "text": "hi",
        "user_id": "1",
        "user_name": "u",
        "lead_id": "123",
        "status_id": 777,
    }

    await worker_mirror.handle_mirror_bot_to_amo(payload)
    await worker_mirror.handle_mirror_bot_to_amo(payload)

    assert queue_mock == [
        {
            "platform": "amo",
            "action": "amo_update_status",
            "lead_id": 123,
            "status_id": 777,
        }
    ]


@pytest.mark.asyncio
async def test_bot_message_sent(monkeypatch):
    conv_id = "lead:123"

    async def fake_ensure_chat_created(**kwargs):
        return conv_id

    called = {}

    async def fake_send_text_from_manager(**kwargs):
        called["args"] = kwargs

    async def fake_with_retry(func, attempts, is_retryable):
        return await func()

    class DummyAmo:
        async def get_lead_with_contacts(self, lead_id):
            return {}

    class DummyAmoClient:
        @staticmethod
        async def create(client):
            return DummyAmo()

    async def fake_check_and_store(key):
        return True

    async def fake_set_conversation(*args, **kwargs):
        return None

    monkeypatch.setattr(worker_mirror, "ensure_chat_created", fake_ensure_chat_created)
    monkeypatch.setattr(worker_mirror, "send_text_from_manager", fake_send_text_from_manager)
    monkeypatch.setattr(worker_mirror, "with_retry", fake_with_retry)
    monkeypatch.setattr(worker_mirror, "AmoClient", DummyAmoClient)
    monkeypatch.setattr(worker_mirror, "check_and_store", fake_check_and_store)
    monkeypatch.setattr(worker_mirror, "set_conversation", fake_set_conversation)

    payload = {
        "text": "hello",
        "user_id": "1",
        "user_name": "u",
        "lead_id": "123",
        "bot_kind": "master",
    }

    await worker_mirror.handle_mirror_bot_to_amo(payload)

    assert called["args"]["text"] == "hello"
    assert called["args"]["conversation_id"] == conv_id
