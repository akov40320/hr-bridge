import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import tg_webhooks


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
    monkeypatch.setattr(tg_webhooks.settings, "TELEGRAM_WEBHOOK_SECRET", "")
    app = build_app(bot, "master", dp, monkeypatch)
    client = TestClient(app)
    r = client.post("/tg/webhook/master", json=sample_update)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert dp.called


def test_factory_no_bot(monkeypatch, sample_update):
    dp = DummyDP()
    monkeypatch.setattr(tg_webhooks.settings, "TELEGRAM_WEBHOOK_SECRET", "")
    app = build_app(None, "operator", dp, monkeypatch)
    client = TestClient(app)
    r = client.post("/tg/webhook/operator", json=sample_update)
    assert r.status_code == 503


def test_factory_bad_secret(monkeypatch, sample_update):
    dp = DummyDP()
    bot = object()
    monkeypatch.setattr(tg_webhooks.settings, "TELEGRAM_WEBHOOK_SECRET", "s3cret")
    app = build_app(bot, "master", dp, monkeypatch)
    client = TestClient(app)
    r = client.post("/tg/webhook/master", json=sample_update)
    assert r.status_code == 401
