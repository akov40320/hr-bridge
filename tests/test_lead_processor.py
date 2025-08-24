import pytest

from app.models import Applicant, IncomingPayload
from app.services import lead_processor


@pytest.mark.asyncio
async def test_enrich_applicant(monkeypatch):
    payload = IncomingPayload(
        platform="hh",
        owner_id="o1",
        applicant=Applicant(id="1", name="кандидат"),
    )

    async def fake_fetch(applicant_id, owner_id, http_client):
        return {
            "phone": "123",
            "city": "Moscow",
            "name": "Ivan",
            "email": "ivan@example.com",
        }

    monkeypatch.setattr(lead_processor.hh_adapt, "fetch_applicant_details", fake_fetch)

    result = await lead_processor.enrich_applicant(payload, None)
    assert result.applicant.phone == "123"
    assert result.applicant.city == "Moscow"
    assert result.applicant.name == "Ivan"
    assert result.applicant.email == "ivan@example.com"


@pytest.mark.asyncio
async def test_enrich_applicant_vacancy_desc(monkeypatch):
    payload = IncomingPayload(
        platform="hh",
        owner_id="o1",
        vacancy_id="vac1",
        vacancy_desc="",
        applicant=Applicant(id="1", name="кандидат"),
    )

    async def fake_fetch_applicant_details(applicant_id, owner_id, http_client):
        return {}

    async def fake_fetch_vacancy_description(vacancy_id, employer_id, client):
        return "Test #мастер vacancy"

    monkeypatch.setattr(
        lead_processor.hh_adapt, "fetch_applicant_details", fake_fetch_applicant_details
    )
    monkeypatch.setattr(
        lead_processor.hh_adapt, "fetch_vacancy_description", fake_fetch_vacancy_description
    )

    result = await lead_processor.enrich_applicant(payload, None)
    assert result.vacancy_desc == "Test #мастер vacancy"

    class DummyClient:
        async def create_leads(self, body):
            return {"_embedded": {"leads": [{"id": 321}]}}

        async def add_tags(self, *a, **kw):
            pass

    async def fake_enrich(*args, **kwargs):
        return None

    async def fake_save_link(**kwargs):
        return None

    monkeypatch.setattr(lead_processor.amo_lead_enrichment, "enrich_lead", fake_enrich)
    monkeypatch.setattr(lead_processor, "save_link", fake_save_link)

    lead_id, kind = await lead_processor.create_lead(result, DummyClient())
    assert lead_id == 321
    assert kind == "master"


@pytest.mark.asyncio
async def test_create_lead(monkeypatch):
    payload = IncomingPayload(
        platform="hh",
        vacancy_title="Title",
        vacancy_desc="",
        raw_text="",
        applicant=Applicant(id="1", name="John", email="j@e.ru"),
        owner_id="own",
        vacancy_id="vac",
    )

    monkeypatch.setattr("app.api.utils.route_kind", lambda **kw: "master")

    class DummyClient:
        async def create_leads(self, body):
            return {"_embedded": {"leads": [{"id": 321}]}}

        async def add_tags(self, *a, **kw):
            pass

    async def fake_enrich(*args, **kwargs):
        assert kwargs.get("email") == "j@e.ru"
        return None

    async def fake_save_link(**kwargs):
        return None

    monkeypatch.setattr(lead_processor.amo_lead_enrichment, "enrich_lead", fake_enrich)
    monkeypatch.setattr(lead_processor, "save_link", fake_save_link)

    lead_id, kind = await lead_processor.create_lead(payload, DummyClient())
    assert lead_id == 321
    assert kind == "master"


@pytest.mark.asyncio
async def test_send_invite(queue_mock):
    payload = IncomingPayload(
        platform="hh",
        owner_id="o1",
        applicant=Applicant(id="resp", name="name"),
        kind="master",
    )

    link = await lead_processor.send_invite(payload, 555)
    assert "start=555" in link
    assert queue_mock and queue_mock[0]["platform"] == "hh"


@pytest.mark.asyncio
async def test_tag_lead():
    stored = {}

    class DummyClient:
        async def add_tags(self, lead_id, tags):
            stored["lead_id"] = lead_id
            stored["tags"] = tags

    await lead_processor.tag_lead(10, "operator", DummyClient())
    assert stored == {"lead_id": 10, "tags": ["type:оператор"]}
