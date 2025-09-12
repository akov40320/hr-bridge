import httpx
import pytest
import yaml

from app.services import hh_autofill
from app.models import Applicant, IncomingPayload


@pytest.mark.asyncio
async def test_stage_rename_updates_mapping(monkeypatch, tmp_path):
    mapping_store = {"1": "response"}
    fake_statuses = []

    mapping_file = tmp_path / "map.yaml"
    mapping_file.write_text(
        yaml.safe_dump({"собеседование": "interview"}, allow_unicode=True)
    )
    monkeypatch.setattr(hh_autofill, "MAPPING_FILE", mapping_file)
    hh_autofill.reload_stage_mapping()

    async def fake_fetch_pipeline_statuses(pipeline_id, client):  # pragma: no cover - simple stub
        return fake_statuses

    class DummySettings:
        AMO_PIPELINE_ID_MASTER = 123
        AMO_PIPELINE_ID_OPERATOR = None

    monkeypatch.setattr(hh_autofill, "_fetch_pipeline_statuses", fake_fetch_pipeline_statuses)
    monkeypatch.setattr(hh_autofill, "get_settings", lambda: DummySettings())

    async def fake_load():
        return mapping_store.copy()

    async def fake_set(mapping):
        nonlocal mapping_store
        mapping_store = mapping.copy()
        return mapping

    monkeypatch.setattr(hh_autofill, "hh_map_load", fake_load)
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
        ("Прошел опрос", "прошелопрос", "interview"),
        ("Отклонён", "отклонен", "discard_by_employer"),
        ("Новый отклик", "новыйотклик", "response"),
        ("Кандидат отказался", "кандидатотказался", "discard_by_applicant"),
        ("Не выходит на связь", "невыходитнасвязь", "discard_no_interaction"),
        ("Вакансия закрыта", "вакансиязакрыта", "discard_vacancy_closed"),
        (
            "Перевод на другую вакансию",
            "переводнадругуювакансию",
            "discard_to_other_vacancy",
        ),
    ],
)
def test_stage_name_normalization_and_mapping(monkeypatch, tmp_path, raw, normalized, code):
    mapping_file = tmp_path / "map.yaml"
    mapping_file.write_text(
        yaml.safe_dump({normalized: code}, allow_unicode=True)
    )
    monkeypatch.setattr(hh_autofill, "MAPPING_FILE", mapping_file)
    hh_autofill.reload_stage_mapping()

    assert hh_autofill._norm_stage_name(raw) == normalized
    assert hh_autofill._STAGE_NAME_TO_HH[normalized] == code


@pytest.mark.asyncio
async def test_enrich_applicant_adds_vacancy_title(monkeypatch):
    import sys, types

    api_pkg = types.ModuleType("app.api")
    utils_mod = types.ModuleType("app.api.utils")

    def route_kind(*, desc: str = "", raw: str = "") -> str:
        return "ignore"

    utils_mod.route_kind = route_kind
    api_pkg.utils = utils_mod
    sys.modules.setdefault("app.api", api_pkg)
    sys.modules.setdefault("app.api.utils", utils_mod)

    from app.services import lead_processor

    payload = IncomingPayload(
        platform="hh",
        owner_id="own",
        applicant=Applicant(id="nid", name="anon"),
        vacancy_id="vac1",
        vacancy_title="",
        vacancy_desc="desc",
    )

    async def fake_fetch_applicant_details(*args, **kwargs):
        return {}

    async def fake_fetch_vacancy_title(vacancy_id, owner_id, client):
        assert vacancy_id == "vac1"
        assert owner_id == "own"
        return "Название"

    monkeypatch.setattr(
        lead_processor.hh_adapt, "fetch_applicant_details", fake_fetch_applicant_details
    )
    monkeypatch.setattr(
        lead_processor.hh_adapt, "fetch_vacancy_title", fake_fetch_vacancy_title
    )

    result = await lead_processor.enrich_applicant(payload, None)
    assert result.vacancy_title == "Название"

