import pytest

import app.api.tasks as tasks


@pytest.mark.asyncio
async def test_handle_task_mirror_bot_to_amo(monkeypatch):
    called = {}

    async def fake_handle(payload):
        called["payload"] = payload

    monkeypatch.setattr(tasks, "handle_mirror_bot_to_amo", fake_handle)

    msg = {
        "platform": "mirror",
        "action": "bot_to_amo",
        "payload": {"text": "hi"},
        "msg_key": "k1",
    }
    await tasks.handle_task(msg)
    assert called["payload"] == {"text": "hi", "msg_key": "k1"}
