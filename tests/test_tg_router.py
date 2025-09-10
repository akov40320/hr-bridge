from types import SimpleNamespace
import pytest
from aiogram import Bot

from app import tg_router
from aiogram.types import Update


class DummySurveyService:
    def __init__(self):
        self.data = {}
        self.finished = None

    async def start(self, user_id: int, bot_kind: str, lead_id: int, identity: str):
        self.data[user_id] = {"lead_id": lead_id, "step": 0}

    async def get(self, user_id: int, bot_kind: str):
        d = self.data.get(user_id)
        if not d:
            return None
        return SimpleNamespace(
            lead_id=d["lead_id"],
            step=d["step"],
            city=d.get("city"),
            experience=d.get("experience"),
            time_pref=d.get("time_pref"),
        )

    async def store_answer(self, user_id: int, bot_kind: str, text: str):
        d = self.data.get(user_id)
        if not d:
            return None
        step = d["step"]
        if step == 0:
            d["city"] = text
        elif step == 1:
            d["experience"] = text
        elif step == 2:
            d["time_pref"] = text
        d["step"] += 1
        return await self.get(user_id, bot_kind)

    async def finish(self, user_id: int, bot_kind: str, lead_id: int, summary: str):
        self.finished = (user_id, bot_kind, lead_id, summary)


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


async def feed(dp, bot, update):
    upd = Update.model_validate(update)
    await dp.feed_update(bot, upd)


@pytest.mark.asyncio
async def test_start(monkeypatch, queue_mock):
    svc = DummySurveyService()
    monkeypatch.setattr(tg_router, "SurveyService", lambda *a, **k: svc)
    async def dummy_upsert(*a, **k):
        return None
    monkeypatch.setattr(tg_router, "upsert_tg_link", dummy_upsert)

    dp = tg_router.make_router("master")
    bot, sent = make_bot()

    update = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 0,
            "chat": {"id": 1, "type": "private"},
            "text": "/start 777",
            "from": {"id": 1, "is_bot": False, "username": "u", "first_name": "U"},
        },
    }

    await feed(dp, bot, update)
    await bot.session.close()

    assert sent and "Здравствуйте" in sent[0]["text"]
    assert queue_mock[-1]["action"] == "bot_to_amo"
    assert queue_mock[-1]["payload"]["lead_id"] == 777


@pytest.mark.asyncio
async def test_text_step(monkeypatch, queue_mock):
    svc = DummySurveyService()
    monkeypatch.setattr(tg_router, "SurveyService", lambda *a, **k: svc)
    async def dummy_upsert(*a, **k):
        return None
    monkeypatch.setattr(tg_router, "upsert_tg_link", dummy_upsert)

    await svc.start(1, "master", 555, "id:1")

    dp = tg_router.make_router("master")
    bot, sent = make_bot()

    update = {
        "update_id": 2,
        "message": {
            "message_id": 2,
            "date": 0,
            "chat": {"id": 1, "type": "private"},
            "text": "Moscow",
            "from": {"id": 1, "is_bot": False, "username": "u", "first_name": "U"},
        },
    }

    await feed(dp, bot, update)
    await bot.session.close()

    assert sent and "Опишите" in sent[0]["text"]
    assert queue_mock[0]["action"] == "tg_to_amo"
    assert queue_mock[1]["action"] == "bot_to_amo"
    assert svc.data[1]["step"] == 1


@pytest.mark.asyncio
async def test_survey_finish(monkeypatch, queue_mock):
    svc = DummySurveyService()
    monkeypatch.setattr(tg_router, "SurveyService", lambda *a, **k: svc)
    async def dummy_upsert(*a, **k):
        return None
    monkeypatch.setattr(tg_router, "upsert_tg_link", dummy_upsert)

    svc.data[1] = {
        "lead_id": 555,
        "step": 2,
        "city": "Moscow",
        "experience": "5y",
    }

    dp = tg_router.make_router("master")
    bot, sent = make_bot()

    update = {
        "update_id": 3,
        "message": {
            "message_id": 3,
            "date": 0,
            "chat": {"id": 1, "type": "private"},
            "text": "tomorrow",
            "from": {"id": 1, "is_bot": False, "username": "u", "first_name": "U"},
        },
    }

    await feed(dp, bot, update)
    await bot.session.close()

    assert sent and "Спасибо" in sent[0]["text"]
    assert queue_mock[0]["action"] == "tg_to_amo"
    assert queue_mock[1]["action"] == "bot_to_amo"
    # finish called with summary
    assert svc.finished and "Итоги опроса" in svc.finished[3]


@pytest.mark.asyncio
async def test_text_no_lead(monkeypatch, queue_mock):
    svc = DummySurveyService()
    monkeypatch.setattr(tg_router, "SurveyService", lambda *a, **k: svc)
    async def dummy_upsert(*a, **k):
        return None
    async def dummy_get(*a, **k):
        return None
    monkeypatch.setattr(tg_router, "upsert_tg_link", dummy_upsert)
    monkeypatch.setattr(tg_router, "get_by_user", dummy_get)

    dp = tg_router.make_router("master")
    bot, sent = make_bot()

    update = {
        "update_id": 4,
        "message": {
            "message_id": 4,
            "date": 0,
            "chat": {"id": 1, "type": "private"},
            "text": "hi",
            "from": {"id": 1, "is_bot": False, "username": "u", "first_name": "U"},
        },
    }

    await feed(dp, bot, update)
    await bot.session.close()

    assert sent and "Нажмите /start" in sent[0]["text"]
    assert queue_mock == []


@pytest.mark.asyncio
async def test_text_session_missing(monkeypatch, queue_mock):
    svc = DummySurveyService()
    monkeypatch.setattr(tg_router, "SurveyService", lambda *a, **k: svc)
    async def dummy_upsert(*a, **k):
        return None
    monkeypatch.setattr(tg_router, "upsert_tg_link", dummy_upsert)

    svc.data[1] = {"lead_id": 555, "step": 0}

    async def store_missing(user_id, bot_kind, text):
        return None

    monkeypatch.setattr(svc, "store_answer", store_missing)

    dp = tg_router.make_router("master")
    bot, sent = make_bot()

    update = {
        "update_id": 5,
        "message": {
            "message_id": 5,
            "date": 0,
            "chat": {"id": 1, "type": "private"},
            "text": "test",
            "from": {"id": 1, "is_bot": False, "username": "u", "first_name": "U"},
        },
    }

    await feed(dp, bot, update)
    await bot.session.close()

    assert sent and "Сессия не найдена" in sent[0]["text"]
    assert queue_mock[0]["action"] == "tg_to_amo"
    assert queue_mock[1]["action"] == "bot_to_amo"
