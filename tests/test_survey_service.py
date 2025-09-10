import types
import pytest

from app.core.config import get_settings
from app.services.survey_service import SurveyService

settings = get_settings()


@pytest.mark.asyncio
async def test_start(monkeypatch, queue_mock):
    called = []

    async def fake_start_or_reset(user_id, bot_kind, lead_id):
        called.append((user_id, bot_kind, lead_id))

    monkeypatch.setattr(
        "app.services.survey_service.start_or_reset_survey", fake_start_or_reset
    )
    monkeypatch.setattr(settings, "AMO_STAGE_ID_MASTER_NEW", 1)
    monkeypatch.setattr(settings, "AMO_STAGE_ID_OPERATOR_NEW", 2)

    svc = SurveyService()
    await svc.start(1, "master", 10, "id:42")

    assert called == [(1, "master", 10)]
    assert len(queue_mock) == 3
    assert queue_mock[0] == {
        "platform": "amo",
        "action": "amo_add_note",
        "payload": {
            "lead_id": 10,
            "text": "[master] Кандидат перешёл в бота (TG id:42).",
        },
    }
    assert queue_mock[1] == {
        "platform": "amo",
        "action": "amo_add_tags",
        "payload": {
            "lead_id": 10,
            "tags": [settings.AMO_TAG_WENT_TO_BOT],
        },
    }
    last = queue_mock[2]
    assert last["platform"] == "amo"
    assert last["action"] == "amo_update_status"
    assert last["payload"]["lead_id"] == 10
    assert last["payload"]["status_id"] == settings.AMO_STAGE_ID_MASTER_NEW
    assert isinstance(last["payload"]["ts"], int)


@pytest.mark.asyncio
async def test_start_operator(monkeypatch, queue_mock):
    called = []

    async def fake_start_or_reset(user_id, bot_kind, lead_id):
        called.append((user_id, bot_kind, lead_id))

    monkeypatch.setattr(
        "app.services.survey_service.start_or_reset_survey", fake_start_or_reset
    )
    monkeypatch.setattr(settings, "AMO_STAGE_ID_MASTER_NEW", 3)
    monkeypatch.setattr(settings, "AMO_STAGE_ID_OPERATOR_NEW", 4)

    svc = SurveyService()
    await svc.start(2, "operator", 20, "id:99")

    assert called == [(2, "operator", 20)]
    assert len(queue_mock) == 3
    assert queue_mock[0] == {
        "platform": "amo",
        "action": "amo_add_note",
        "payload": {
            "lead_id": 20,
            "text": "[operator] Кандидат перешёл в бота (TG id:99).",
        },
    }
    assert queue_mock[1] == {
        "platform": "amo",
        "action": "amo_add_tags",
        "payload": {
            "lead_id": 20,
            "tags": [settings.AMO_TAG_WENT_TO_BOT],
        },
    }
    last = queue_mock[2]
    assert last["platform"] == "amo"
    assert last["action"] == "amo_update_status"
    assert last["payload"]["lead_id"] == 20
    assert last["payload"]["status_id"] == settings.AMO_STAGE_ID_OPERATOR_NEW
    assert isinstance(last["payload"]["ts"], int)


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
@pytest.mark.parametrize(
    "bot_kind, stage_attr, stage_value",
    [
        ("master", "AMO_STAGE_ID_MASTER_SURVEY", 5),
        ("operator", "AMO_STAGE_ID_OPERATOR_SURVEY", 6),
    ],
)
async def test_finish(bot_kind, stage_attr, stage_value, monkeypatch, queue_mock):
    deleted = []

    async def fake_delete(user_id, b_kind):
        deleted.append((user_id, b_kind))

    monkeypatch.setattr("app.services.survey_service.delete_survey", fake_delete)
    monkeypatch.setattr(settings, stage_attr, stage_value)

    svc = SurveyService()
    await svc.finish(3, bot_kind, 33, "summary")
    assert len(queue_mock) == 3
    assert queue_mock[0] == {
        "platform": "amo",
        "action": "amo_add_tags",
        "payload": {
            "lead_id": 33,
            "tags": [settings.AMO_TAG_SURVEY_DONE],
        },
    }
    assert queue_mock[1] == {
        "platform": "amo",
        "action": "amo_add_note",
        "payload": {
            "lead_id": 33,
            "text": f"[{bot_kind}] summary",
        },
    }
    last = queue_mock[2]
    assert last["platform"] == "amo"
    assert last["action"] == "amo_update_status"
    assert last["payload"]["lead_id"] == 33
    assert last["payload"]["status_id"] == stage_value
    assert isinstance(last["payload"]["ts"], int)
    assert deleted == [(3, bot_kind)]
