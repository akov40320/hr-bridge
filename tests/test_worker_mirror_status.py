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

    monkeypatch.setattr(worker_mirror, "ensure_chat_created", fake_ensure_chat_created)
    monkeypatch.setattr(worker_mirror, "check_and_store", fake_check_and_store)

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
