import pytest

from app.services import amo_lead_enrichment
from app.core.config import get_settings

settings = get_settings()


class DummyAmo:
    def __init__(self):
        self.calls = {}

    async def create_contact(self, name, phone):
        self.calls["create_contact"] = (name, phone)
        return {"_embedded": {"contacts": [{"id": 1}]}}

    async def link_contact_to_lead(self, lead_id, contact_id):
        self.calls["link_contact_to_lead"] = (lead_id, contact_id)

    async def update_lead_custom_fields(self, lead_id, cf):
        self.calls["update_lead_custom_fields"] = (lead_id, cf)

    async def add_note(self, lead_id, note):
        self.calls["add_note"] = (lead_id, note)


@pytest.mark.asyncio
async def test_enrich_lead_updates_fields(monkeypatch):
    amo = DummyAmo()

    monkeypatch.setattr(settings, "AMO_CF_LEAD_CITY_ID", 1)
    monkeypatch.setattr(settings, "AMO_CF_LEAD_VACANCY_TITLE_ID", 2)
    monkeypatch.setattr(settings, "AMO_CF_LEAD_APPLICANT_PHONE_ID", 3)
    monkeypatch.setattr(settings, "AMO_CF_LEAD_APPLICANT_NAME_ID", 4)

    await amo_lead_enrichment.enrich_lead(
        amo,
        10,
        applicant_name="Ivan",
        phone="123",
        city="Moscow",
        vacancy_title="Plumber",
    )

    assert amo.calls["update_lead_custom_fields"] == (
        10,
        {1: "Moscow", 2: "Plumber", 3: "123", 4: "Ivan"},
    )
    assert "add_note" not in amo.calls


@pytest.mark.asyncio
async def test_enrich_lead_creates_note_when_no_cfs(monkeypatch):
    amo = DummyAmo()

    monkeypatch.setattr(settings, "AMO_CF_LEAD_CITY_ID", 0)
    monkeypatch.setattr(settings, "AMO_CF_LEAD_VACANCY_TITLE_ID", 0)
    monkeypatch.setattr(settings, "AMO_CF_LEAD_APPLICANT_PHONE_ID", 0)
    monkeypatch.setattr(settings, "AMO_CF_LEAD_APPLICANT_NAME_ID", 0)

    await amo_lead_enrichment.enrich_lead(
        amo,
        20,
        applicant_name="Anna",
        phone="456",
        city="SPb",
        vacancy_title="Operator",
    )

    assert "add_note" in amo.calls
    lead_id, note = amo.calls["add_note"]
    assert lead_id == 20
    assert "Anna" in note and "456" in note and "SPb" in note and "Operator" in note
