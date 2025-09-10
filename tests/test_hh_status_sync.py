import pytest

from app.services import hh_status_sync


class DummyQueue:
    def __init__(self):
        self.tasks = []

    async def publish_task(self, payload):
        self.tasks.append(payload)


@pytest.mark.asyncio
async def test_sync_hh_status_basic(monkeypatch):
    monkeypatch.setattr(hh_status_sync, "hh_map_get", lambda sid: "phone_interview")

    class S:
        AMO_CF_REFUSAL_REASON_ID = None

    monkeypatch.setattr(hh_status_sync, "get_settings", lambda: S())

    q = DummyQueue()
    await hh_status_sync.sync_hh_status(
        1,
        10,
        {"external_id": "nid", "owner_id": "oid"},
        http_client=None,
        queue_client=q,
    )

    assert q.tasks == [
        {
            "platform": "hh",
            "action": "set_state",
            "payload": {
                "external_id": "nid",
                "target_state": "phone_interview",
                "owner_id": "oid",
            },
        }
    ]


@pytest.mark.asyncio
async def test_sync_hh_status_refusal_mapping(monkeypatch):
    monkeypatch.setattr(hh_status_sync, "hh_map_get", lambda sid: "discard_by_employer")

    class S:
        AMO_CF_REFUSAL_REASON_ID = 5

    monkeypatch.setattr(hh_status_sync, "get_settings", lambda: S())

    async def fake_fetch(lead_id, client, field_id):
        return "не выходит на связь"

    monkeypatch.setattr(hh_status_sync, "_fetch_refusal_reason", fake_fetch)

    q = DummyQueue()
    await hh_status_sync.sync_hh_status(
        1,
        10,
        {"external_id": "nid", "owner_id": "oid"},
        http_client=None,
        queue_client=q,
    )

    assert q.tasks[0]["payload"]["target_state"] == "discard_no_interaction"
