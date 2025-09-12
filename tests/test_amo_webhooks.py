import json
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from unittest.mock import AsyncMock

from app.api import amo_webhooks


def _json_request(data: dict) -> Request:
    body = json.dumps(data).encode()
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", b"application/json")],
    }
    return Request(scope, receive)


def _form_request(data: dict) -> Request:
    body = urlencode(data).encode()
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
    }
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_parse_status_events_json():
    payload = {
        "leads": {
            "status": [
                {"id": "1", "status_id": "10"},
                {"id": "2", "new_status_id": "20"},
            ]
        }
    }
    req = _json_request(payload)
    events = await amo_webhooks.parse_status_events(req)
    assert events == [(1, 10), (2, 20)]


@pytest.mark.asyncio
async def test_parse_status_events_form():
    form_data = {
        "leads[status][0][id]": "3",
        "leads[status][0][status_id]": "30",
        "leads[status][1][id]": "4",
        "leads[status][1][status_id]": "40",
    }
    req = _form_request(form_data)
    events = await amo_webhooks.parse_status_events(req)
    assert events == [(3, 30), (4, 40)]


@pytest.mark.asyncio
async def test_parse_status_events_form_new_status_id():
    form_data = {
        "leads[status][0][id]": "5",
        "leads[status][0][new_status_id]": "50",
    }
    req = _form_request(form_data)
    events = await amo_webhooks.parse_status_events(req)
    assert events == [(5, 50)]


@pytest.mark.asyncio
async def test_handle_hh_event_unknown_status(monkeypatch, caplog):
    async def fake_map_get(_):
        return None

    monkeypatch.setattr(amo_webhooks, "hh_map_get", fake_map_get)

    queue = type("Q", (), {"publish_task": AsyncMock()})()
    link = {"external_id": "ext", "owner_id": 1}

    with caplog.at_level("INFO"):
        await amo_webhooks.handle_hh_event(1, 2, link, object(), queue)

    queue.publish_task.assert_awaited_once_with({"platform": "system", "action": "hh_autofill"})
    assert "hh_autofill" in caplog.text
