import json
import pytest

from app.services.payload_parsers import parse_hh_payload, parse_avito_payload


def test_parse_hh_payload_ok():
    raw = json.dumps(
        {
            "response": {
                "id": "resp1",
                "vacancy": {"id": "vac1", "name": "Vac", "description": "Desc"},
                "applicant": {"name": "John"},
            },
            "employer": {"id": "emp1"},
        }
    ).encode()

    payload = parse_hh_payload(raw)
    assert payload["platform"] == "hh"
    assert payload["owner_id"] == "emp1"
    assert payload["vacancy_id"] == "vac1"
    assert payload["applicant"] == {"id": "resp1", "name": "John"}


def test_parse_hh_payload_missing_id():
    raw = json.dumps({"response": {}}).encode()
    with pytest.raises(ValueError):
        parse_hh_payload(raw)


def test_parse_hh_payload_bad_json():
    with pytest.raises(ValueError):
        parse_hh_payload(b"{bad json")


def test_parse_avito_payload_ok():
    raw = json.dumps(
        {
            "payload": {
                "value": {
                    "chat_id": "chat1",
                    "content": {"text": "hi"},
                    "item": {"id": "item1", "title": "Vac", "description": "Desc"},
                    "user_id": "u1",
                },
                "account_id": "acc1",
            }
        }
    ).encode()

    payload = parse_avito_payload(raw)
    assert payload["platform"] == "avito"
    assert payload["owner_id"] == "acc1"
    assert payload["vacancy_id"] == "item1"
    assert payload["applicant"] == {"id": "chat1", "name": "user:u1"}
    assert payload["raw_text"] == "hi"


def test_parse_avito_payload_missing_chat_id():
    raw = json.dumps({"payload": {"value": {}}}).encode()
    with pytest.raises(ValueError):
        parse_avito_payload(raw)


def test_parse_avito_payload_bad_json():
    with pytest.raises(ValueError):
        parse_avito_payload(b"not json")
