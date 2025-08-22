import types
import pytest

from app.core.config import settings
from app.services.survey_service import SurveyService


@pytest.mark.asyncio
async def test_start(monkeypatch):
    called = []

    async def fake_start_or_reset(user_id, bot_kind, lead_id):
        called.append((user_id, bot_kind, lead_id))

    monkeypatch.setattr(
        "app.services.survey_service.start_or_reset_survey", fake_start_or_reset
    )

    published = []

    async def fake_publish(payload):
        published.append(payload)

    monkeypatch.setattr("app.services.survey.publish_task", fake_publish)

    svc = SurveyService()
    await svc.start(1, "bot", 10, "id:42")

    assert called == [(1, "bot", 10)]
    assert published == [
        {
            "platform": "amo",
            "action": "amo_add_note",
            "lead_id": 10,
            "text": "[bot] Кандидат перешёл в бота (TG id:42).",
        },
        {
            "platform": "amo",
            "action": "amo_add_tags",
            "lead_id": 10,
            "tags": [settings.AMO_TAG_WENT_TO_BOT],
        },
    ]


@pytest.mark.asyncio
async def test_store_answer(monkeypatch):
    called = []

    async def fake_store(user_id, bot_kind, text):
        called.append((user_id, bot_kind, text))
        return types.SimpleNamespace(answer=text)

    monkeypatch.setattr(
        "app.services.survey_service.store_answer_and_advance", fake_store
    )

    svc = SurveyService()
    res = await svc.store_answer(2, "bot2", "hi")

    assert called == [(2, "bot2", "hi")]
    assert res.answer == "hi"


@pytest.mark.asyncio
async def test_finish(monkeypatch):
    deleted = []

    async def fake_delete(user_id, bot_kind):
        deleted.append((user_id, bot_kind))

    monkeypatch.setattr("app.services.survey_service.delete_survey", fake_delete)

    published = []

    async def fake_publish(payload):
        published.append(payload)

    monkeypatch.setattr("app.services.survey_service.publish_task", fake_publish)

    svc = SurveyService()
    await svc.finish(3, "b3", 33, "summary")

    assert published == [
        {
            "platform": "amo",
            "action": "amo_add_tags",
            "lead_id": 33,
            "tags": [settings.AMO_TAG_SURVEY_DONE],
        },
        {
            "platform": "amo",
            "action": "amo_add_note",
            "lead_id": 33,
            "text": "[b3] summary",
        },
    ]
    assert deleted == [(3, "b3")]
