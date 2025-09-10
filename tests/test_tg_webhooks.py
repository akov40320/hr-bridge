import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from aiogram import Bot
from types import SimpleNamespace

from app.api import tg_webhooks
from app import tg_router


class DummyDP:
    def __init__(self):
        self.called = False
        self.bot = None
        self.update = None

    async def feed_update(self, bot, update):
        self.called = True
        self.bot = bot
        self.update = update


@pytest.fixture
def sample_update():
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 0,
            "chat": {"id": 1, "type": "private"},
            "text": "hi",
            "from": {"id": 1, "is_bot": False, "first_name": "x"},
        },
    }


def build_app(bot, kind, dp, monkeypatch):
    monkeypatch.setattr(tg_webhooks, "make_router", lambda k: dp)
    handler = tg_webhooks.make_tg_webhook(bot, kind)
    app = FastAPI()
    app.post(f"/tg/webhook/{kind}")(handler)
    return app


def test_factory_success(monkeypatch, sample_update):
    dp = DummyDP()
    bot = object()
    monkeypatch.setattr(
        tg_webhooks.settings, "TELEGRAM_WEBHOOK_SECRET", SecretStr("")
    )
    app = build_app(bot, "master", dp, monkeypatch)
    client = TestClient(app)
    r = client.post("/tg/webhook/master", json=sample_update)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert dp.called


def test_factory_no_bot(monkeypatch, sample_update):
    dp = DummyDP()
    monkeypatch.setattr(
        tg_webhooks.settings, "TELEGRAM_WEBHOOK_SECRET", SecretStr("")
    )
    app = build_app(None, "operator", dp, monkeypatch)
    client = TestClient(app)
    r = client.post("/tg/webhook/operator", json=sample_update)
    assert r.status_code == 503


def test_factory_bad_secret(monkeypatch, sample_update):
    dp = DummyDP()
    bot = object()
    monkeypatch.setattr(
        tg_webhooks.settings, "TELEGRAM_WEBHOOK_SECRET", SecretStr("s3cret")
    )
    app = build_app(bot, "master", dp, monkeypatch)
    client = TestClient(app)
    r = client.post("/tg/webhook/master", json=sample_update)
    assert r.status_code == 401


def _build_admin_app():
    app = FastAPI()
    app.include_router(tg_webhooks.admin_tg)
    return app


def test_set_webhooks(monkeypatch):
    class DummyBot:
        instances = []

        def __init__(self, token):
            self.token = token
            self.calls = []
            DummyBot.instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def set_webhook(self, **kwargs):
            self.calls.append(("set_webhook", kwargs))
            return "ok"

    monkeypatch.setattr(tg_webhooks, "Bot", DummyBot)
    monkeypatch.setattr(tg_webhooks, "tokens", {"m": "token"})
    monkeypatch.setattr(tg_webhooks.settings, "TELEGRAM_WEBHOOK_BASE", "https://example")
    monkeypatch.setattr(
        tg_webhooks.settings, "TELEGRAM_WEBHOOK_SECRET", SecretStr("s3cr")
    )
    monkeypatch.setattr(tg_webhooks.settings, "ADMIN_TOKEN", SecretStr("secret"))

    app = _build_admin_app()
    client = TestClient(app)
    r = client.post("/admin/tg/set-webhooks", headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "set": {"m": "ok"}}

    assert len(DummyBot.instances) == 1
    call = DummyBot.instances[0].calls[0]
    assert call[0] == "set_webhook"
    assert call[1]["url"] == "https://example/tg/webhook/m"
    assert call[1]["secret_token"] == "s3cr"
    assert call[1]["allowed_updates"] == ["message"]
    assert call[1]["drop_pending_updates"] is True


def test_set_webhooks_no_base(monkeypatch):
    class DummyBot:
        instances = []

        def __init__(self, token):
            DummyBot.instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr(tg_webhooks, "Bot", DummyBot)
    monkeypatch.setattr(tg_webhooks, "tokens", {"m": "token"})
    monkeypatch.setattr(tg_webhooks.settings, "TELEGRAM_WEBHOOK_BASE", "")
    monkeypatch.setattr(tg_webhooks.settings, "ADMIN_TOKEN", SecretStr("secret"))

    app = _build_admin_app()
    client = TestClient(app)
    r = client.post("/admin/tg/set-webhooks", headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "TELEGRAM_WEBHOOK_BASE is empty"}
    assert DummyBot.instances == []


def test_delete_webhooks(monkeypatch):
    class DummyBot:
        instances = []

        def __init__(self, token):
            self.calls = []
            DummyBot.instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def delete_webhook(self, **kwargs):
            self.calls.append(("delete_webhook", kwargs))
            return True

    monkeypatch.setattr(tg_webhooks, "Bot", DummyBot)
    monkeypatch.setattr(tg_webhooks, "tokens", {"m": "token"})
    monkeypatch.setattr(tg_webhooks.settings, "ADMIN_TOKEN", SecretStr("secret"))

    app = _build_admin_app()
    client = TestClient(app)
    r = client.post("/admin/tg/delete-webhooks", headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "results": {"m": True}}

    assert len(DummyBot.instances) == 1
    call = DummyBot.instances[0].calls[0]
    assert call[0] == "delete_webhook"
    assert call[1] == {"drop_pending_updates": True}


def test_webhook_info(monkeypatch):
    class DummyBot:
        instances = []

        def __init__(self, token):
            self.calls = []
            DummyBot.instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def get_webhook_info(self):
            self.calls.append(("get_webhook_info", {}))
            return {"url": "info"}

    monkeypatch.setattr(tg_webhooks, "Bot", DummyBot)
    monkeypatch.setattr(tg_webhooks, "tokens", {"m": "token"})
    monkeypatch.setattr(tg_webhooks.settings, "ADMIN_TOKEN", SecretStr("secret"))

    app = _build_admin_app()
    client = TestClient(app)
    r = client.get("/admin/tg/webhook-info", headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "info": {"m": {"url": "info"}}}

    assert len(DummyBot.instances) == 1
    call = DummyBot.instances[0].calls[0]
    assert call[0] == "get_webhook_info"


class DummySurveyService:
    """Minimal survey service used to track start calls."""

    def __init__(self):
        self.data = {}

    async def start(self, user_id: int, bot_kind: str, lead_id: int, identity: str):
        self.data[user_id] = {"lead_id": lead_id}

    async def get(self, user_id: int, bot_kind: str):
        return None


class DummySession:
    def __init__(self):
        self.sent = []

    async def __call__(self, bot, method, timeout=None):
        self.sent.append({"chat_id": getattr(method, "chat_id", None), "text": getattr(method, "text", "")})
        return True

    async def close(self):
        pass


def make_bot():
    session = DummySession()
    bot = Bot("42:TEST", session=session)
    return bot, session.sent


def test_webhook_creates_task(monkeypatch, queue_mock):
    svc = DummySurveyService()
    monkeypatch.setattr(tg_router, "SurveyService", lambda *a, **k: svc)

    async def dummy_upsert(*a, **k):
        return None

    monkeypatch.setattr(tg_router, "upsert_tg_link", dummy_upsert)

    bot, _ = make_bot()
    dp = tg_router.make_router("master")

    # ensure webhook uses our dispatcher
    monkeypatch.setattr(tg_webhooks, "make_router", lambda k: dp)
    monkeypatch.setattr(tg_webhooks.settings, "TELEGRAM_WEBHOOK_SECRET", SecretStr(""))

    app = FastAPI()
    app.post("/tg/webhook/master")(tg_webhooks.make_tg_webhook(bot, "master"))
    client = TestClient(app)

    update = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 0,
            "chat": {"id": 1, "type": "private"},
            "text": "/start 42",
            "from": {"id": 1, "is_bot": False, "username": "u", "first_name": "U"},
        },
    }

    r = client.post("/tg/webhook/master", json=update)
    assert r.status_code == 200
    assert queue_mock and queue_mock[0]["action"] == "bot_to_amo"
    assert queue_mock[0]["payload"]["lead_id"] == 42


def test_webhook_operator_routing(monkeypatch, queue_mock):
    svc = DummySurveyService()
    monkeypatch.setattr(tg_router, "SurveyService", lambda *a, **k: svc)

    async def dummy_upsert(*a, **k):
        return None

    async def dummy_get_by_user(user_id, bot_kind):
        return SimpleNamespace(lead_id=77, conversation_id=None)

    monkeypatch.setattr(tg_router, "upsert_tg_link", dummy_upsert)
    monkeypatch.setattr(tg_router, "get_by_user", dummy_get_by_user)

    bot, _ = make_bot()
    dp = tg_router.make_router("operator")

    monkeypatch.setattr(tg_webhooks, "make_router", lambda k: dp)
    monkeypatch.setattr(tg_webhooks.settings, "TELEGRAM_WEBHOOK_SECRET", SecretStr(""))

    app = FastAPI()
    app.post("/tg/webhook/operator")(tg_webhooks.make_tg_webhook(bot, "operator"))
    client = TestClient(app)

    update = {
        "update_id": 2,
        "message": {
            "message_id": 2,
            "date": 0,
            "chat": {"id": 1, "type": "private"},
            "text": "hi",
            "from": {"id": 1, "is_bot": False, "username": "u", "first_name": "U"},
        },
    }

    r = client.post("/tg/webhook/operator", json=update)
    assert r.status_code == 200
    assert queue_mock and queue_mock[0]["payload"]["bot_kind"] == "operator"
    assert queue_mock[0]["payload"]["lead_id"] == 77
