from app.api import hh_incoming, _webhook_common
from app.models import IncomingPayload, Applicant


def _payload() -> IncomingPayload:
    return IncomingPayload(platform="hh", owner_id="1", applicant=Applicant(id="a", name="b"))


def test_webhook_success(monkeypatch, client):
    async def fake_check(key):
        return True

    monkeypatch.setattr(_webhook_common, "check_and_store", fake_check)
    monkeypatch.setattr(hh_incoming, "parse_hh_payload", lambda raw: _payload())

    async def fake_enrich(payload, http_client):
        return payload

    monkeypatch.setattr(_webhook_common, "enrich_applicant", fake_enrich)

    async def fake_create_lead(payload, amo):
        return 777, "kind"

    monkeypatch.setattr(_webhook_common, "create_lead", fake_create_lead)

    async def fake_amo_create(cls, client):
        return object()
    monkeypatch.setattr(_webhook_common.AmoClient, "create", classmethod(fake_amo_create))

    called = {}

    async def fake_send_invite(payload, lead_id):
        called["invite"] = lead_id

    async def fake_tag_lead(lead_id, kind, amo):
        called["tag"] = kind

    monkeypatch.setattr(_webhook_common, "send_invite", fake_send_invite)
    monkeypatch.setattr(_webhook_common, "tag_lead", fake_tag_lead)

    r = client.post("/webhooks/hh/1", data=b"{}")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "lead_id": 777}
    assert called["invite"] == 777
    assert called["tag"] == "kind"


def test_webhook_duplicate(monkeypatch, client):
    async def fake_check(key):
        return False

    monkeypatch.setattr(_webhook_common, "check_and_store", fake_check)

    called = False

    def fake_parse(raw):
        nonlocal called
        called = True
        return _payload()

    monkeypatch.setattr(hh_incoming, "parse_hh_payload", fake_parse)

    r = client.post("/webhooks/hh/1", data=b"{}")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "duplicate": True}
    assert not called


def test_webhook_bad_payload(monkeypatch, client):
    async def fake_check(key):
        return True

    monkeypatch.setattr(_webhook_common, "check_and_store", fake_check)

    def fake_parse(raw):
        raise ValueError("bad")

    monkeypatch.setattr(hh_incoming, "parse_hh_payload", fake_parse)

    r = client.post("/webhooks/hh/1", data=b"{}")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "skipped": True}


def test_webhook_ignored(monkeypatch, client):
    async def fake_check(key):
        return True

    monkeypatch.setattr(_webhook_common, "check_and_store", fake_check)
    monkeypatch.setattr(hh_incoming, "parse_hh_payload", lambda raw: _payload())

    async def fake_enrich(payload, http_client):
        return payload

    monkeypatch.setattr(_webhook_common, "enrich_applicant", fake_enrich)

    async def fake_create_lead(payload, amo):
        return None, "ignore"

    monkeypatch.setattr(_webhook_common, "create_lead", fake_create_lead)

    async def fake_amo_create(cls, client):
        return object()
    monkeypatch.setattr(_webhook_common.AmoClient, "create", classmethod(fake_amo_create))

    async def fake_send_invite(*args, **kwargs):
        raise AssertionError("send_invite should not be called")

    async def fake_tag_lead(*args, **kwargs):
        raise AssertionError("tag_lead should not be called")

    monkeypatch.setattr(_webhook_common, "send_invite", fake_send_invite)
    monkeypatch.setattr(_webhook_common, "tag_lead", fake_tag_lead)

    r = client.post("/webhooks/hh/1", data=b"{}")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "ignored": True, "reason": "no-keywords"}


def test_webhook_queued(monkeypatch, client):
    async def fake_check(key):
        return True

    monkeypatch.setattr(_webhook_common, "check_and_store", fake_check)
    monkeypatch.setattr(hh_incoming, "parse_hh_payload", lambda raw: _payload())

    async def fake_enrich(payload, http_client):
        return payload

    monkeypatch.setattr(_webhook_common, "enrich_applicant", fake_enrich)

    async def fake_create_lead(payload, amo):
        return None, "master"

    monkeypatch.setattr(_webhook_common, "create_lead", fake_create_lead)

    async def fake_amo_create(cls, client):
        return object()
    monkeypatch.setattr(_webhook_common.AmoClient, "create", classmethod(fake_amo_create))

    async def fake_send_invite(*args, **kwargs):
        raise AssertionError("send_invite should not be called")

    async def fake_tag_lead(*args, **kwargs):
        raise AssertionError("tag_lead should not be called")

    monkeypatch.setattr(_webhook_common, "send_invite", fake_send_invite)
    monkeypatch.setattr(_webhook_common, "tag_lead", fake_tag_lead)

    r = client.post("/webhooks/hh/1", data=b"{}")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "queued": True, "reason": "reauth_required"}


def test_webhook_enrich_error(monkeypatch, client):
    async def fake_check(key):
        return True

    monkeypatch.setattr(_webhook_common, "check_and_store", fake_check)
    monkeypatch.setattr(hh_incoming, "parse_hh_payload", lambda raw: _payload())

    async def boom(payload, http_client):
        raise RuntimeError("boom")

    monkeypatch.setattr(_webhook_common, "enrich_applicant", boom)

    r = client.post("/webhooks/hh/1", data=b"{}")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "internal_error"}


def test_webhook_create_lead_error(monkeypatch, client):
    async def fake_check(key):
        return True

    monkeypatch.setattr(_webhook_common, "check_and_store", fake_check)
    monkeypatch.setattr(hh_incoming, "parse_hh_payload", lambda raw: _payload())

    async def fake_enrich(payload, http_client):
        return payload

    monkeypatch.setattr(_webhook_common, "enrich_applicant", fake_enrich)

    async def fake_amo_create(cls, client):
        return object()

    monkeypatch.setattr(_webhook_common.AmoClient, "create", classmethod(fake_amo_create))

    async def boom(payload, amo):
        raise RuntimeError("boom")

    monkeypatch.setattr(_webhook_common, "create_lead", boom)

    r = client.post("/webhooks/hh/1", data=b"{}")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "internal_error"}


def test_webhook_tag_error(monkeypatch, client):
    async def fake_check(key):
        return True

    monkeypatch.setattr(_webhook_common, "check_and_store", fake_check)
    monkeypatch.setattr(hh_incoming, "parse_hh_payload", lambda raw: _payload())

    async def fake_enrich(payload, http_client):
        return payload

    monkeypatch.setattr(_webhook_common, "enrich_applicant", fake_enrich)

    async def fake_amo_create(cls, client):
        return object()

    monkeypatch.setattr(_webhook_common.AmoClient, "create", classmethod(fake_amo_create))

    async def fake_create_lead(payload, amo):
        return 123, "kind"

    monkeypatch.setattr(_webhook_common, "create_lead", fake_create_lead)

    called = {}

    async def fake_send_invite(payload, lead_id):
        called["invite"] = lead_id

    async def boom(lead_id, kind, amo):
        raise RuntimeError("boom")

    monkeypatch.setattr(_webhook_common, "send_invite", fake_send_invite)
    monkeypatch.setattr(_webhook_common, "tag_lead", boom)

    r = client.post("/webhooks/hh/1", data=b"{}")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "internal_error"}
    assert called["invite"] == 123
