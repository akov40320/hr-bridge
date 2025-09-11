import httpx
import pytest

from app.services import hh_autofill


@pytest.mark.asyncio
async def test_stage_rename_updates_mapping(monkeypatch):
    mapping_store = {"1": "response"}
    fake_statuses = []

    async def fake_fetch_pipeline_statuses(pipeline_id, client):  # pragma: no cover - simple stub
        return fake_statuses

    class DummySettings:
        AMO_PIPELINE_ID_MASTER = 123
        AMO_PIPELINE_ID_OPERATOR = None

    monkeypatch.setattr(hh_autofill, "_fetch_pipeline_statuses", fake_fetch_pipeline_statuses)
    monkeypatch.setattr(hh_autofill, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(hh_autofill, "hh_map_load", lambda: mapping_store.copy())

    def fake_set(mapping):
        nonlocal mapping_store
        mapping_store = mapping.copy()
        return mapping

    monkeypatch.setattr(hh_autofill, "hh_map_set", fake_set)

    fake_statuses = [{"id": 1, "name": "Собеседование"}]
    async with httpx.AsyncClient() as client:
        result = await hh_autofill.autofill_hh_mapping(client)
    assert result == {"1": "interview"}

    fake_statuses = [{"id": 1, "name": "Другая"}]
    async with httpx.AsyncClient() as client:
        result = await hh_autofill.autofill_hh_mapping(client)
    assert result == {}


@pytest.mark.parametrize(
    "raw, normalized, code",
    [
        ("Принят", "принят", "hired"),
        ("Прошел опрос", "прошелопрос", "phone_interview"),
        ("Отклонён", "отклонен", "discard_by_employer"),
    ],
)
def test_stage_name_normalization_and_mapping(raw, normalized, code):
    assert hh_autofill._norm_stage_name(raw) == normalized
    assert hh_autofill._STAGE_NAME_TO_HH[normalized] == code

