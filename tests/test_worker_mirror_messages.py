import pytest
from types import SimpleNamespace

from app.services.worker import mirror as worker_mirror
from pydantic import SecretStr


@pytest.mark.asyncio
async def test_handle_mirror_amo_to_tg(monkeypatch):
    calls = []

    async def fake_send(bot, uid, text):
        calls.append((bot.token, uid, text))

    class DummyBot:
        def __init__(self, token):
            self.token = token

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummySettings:
        TELEGRAM_MASTER_BOT_TOKEN = SecretStr("m_token")
        TELEGRAM_OPERATOR_BOT_TOKEN = SecretStr("o_token")

    monkeypatch.setattr(worker_mirror, "tg_send_with_retry", fake_send)
    monkeypatch.setattr(worker_mirror, "Bot", DummyBot)
    monkeypatch.setattr(worker_mirror, "get_settings", lambda: DummySettings())

    payload = {"bot_kind": "master", "user_id": "42", "text": "hi"}
    await worker_mirror.handle_mirror_amo_to_tg(payload)

    assert calls == [("m_token", 42, "hi")]


@pytest.mark.asyncio
async def test_handle_mirror_tg_to_amo(monkeypatch):
    calls = {"note": [], "send": [], "set_conv": []}

    class DummyAmo:
        async def add_note(self, lead_id, text):
            calls["note"].append((lead_id, text))

    async def fake_create(client):
        return DummyAmo()

    async def fake_send_text_from_client(**kwargs):
        calls["send"].append(kwargs)
        return "cid"

    async def fake_set_conversation(user_id, bot_kind, conv_id):
        calls["set_conv"].append((user_id, bot_kind, conv_id))

    async def fake_with_retry(func, *args, **kwargs):
        return await func()

    monkeypatch.setattr(worker_mirror, "AmoClient", SimpleNamespace(create=fake_create))
    monkeypatch.setattr(worker_mirror, "send_text_from_client", fake_send_text_from_client)
    monkeypatch.setattr(worker_mirror, "set_conversation", fake_set_conversation)
    monkeypatch.setattr(worker_mirror, "get_http_client", lambda: object())
    monkeypatch.setattr(worker_mirror, "with_retry", fake_with_retry)

    payload = {
        "lead_id": "1",
        "text": "hello",
        "tg_user_id": "2",
        "bot_kind": "master",
        "tg_user_name": "u",
    }
    await worker_mirror.handle_mirror_tg_to_amo(payload)

    assert calls["note"] == [(1, "[TG->master] hello")]
    assert calls["send"][0]["lead_id"] == 1
    assert calls["set_conv"] == [(2, "master", "cid")]
