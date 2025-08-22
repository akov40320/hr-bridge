import json
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.amo_webhooks import parse_status_events


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
    events = await parse_status_events(req)
    assert events == [(1, 10), (2, 20)]


@pytest.mark.asyncio
async def test_parse_status_events_form_error():
    form_data = {
        "leads[status][0][id]": "3",
        "leads[status][0][status_id]": "30",
        "leads[status][1][id]": "4",
        "leads[status][1][status_id]": "40",
    }
    req = _form_request(form_data)
    with pytest.raises(HTTPException) as exc:
        await parse_status_events(req)
    assert exc.value.status_code == 400
