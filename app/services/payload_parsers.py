import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def parse_hh_payload(raw: bytes) -> Dict[str, Any]:
    """Parse raw HeadHunter webhook data into normalized payload.

    Args:
        raw: Raw HTTP body bytes.

    Returns:
        Normalized payload dictionary suitable for `_process_incoming`.

    Raises:
        ValueError: If the JSON is malformed or required identifiers are missing.
    """
    try:
        data = json.loads(raw.decode() or "{}")
    except Exception as exc:  # pragma: no cover - log only
        logger.warning("HH payload parse error: %s", exc)
        raise ValueError("invalid json") from exc

    obj = (
        data.get("object")
        or data.get("negotiation")
        or data.get("response")
        or data.get("payload")
        or {}
    )

    response_id = str(
        obj.get("id")
        or data.get("response_id")
        or obj.get("negotiation_id")
        or ""
    )

    vacancy = obj.get("vacancy") or {}
    applicant = obj.get("applicant") or obj.get("resume", {}).get("owner", {}) or {}

    vacancy_id = str(vacancy.get("id") or data.get("vacancy_id") or "")
    vacancy_title = vacancy.get("name") or data.get("vacancy_title") or ""
    vacancy_desc = vacancy.get("description") or data.get("vacancy_description") or ""
    applicant_name = (
        applicant.get("name") or applicant.get("first_name") or ""
    ).strip() or "кандидат"

    owner_id = (
        str(
            data.get("employer", {}).get("id")
            or obj.get("employer", {}).get("id")
            or ""
        )
        or None
    )

    if not response_id:
        raise ValueError("missing response_id")

    return {
        "platform": "hh",
        "owner_id": owner_id,
        "vacancy_id": vacancy_id,
        "vacancy_title": vacancy_title,
        "vacancy_desc": vacancy_desc,
        "applicant": {"id": response_id, "name": applicant_name},
    }


def parse_avito_payload(raw: bytes) -> Dict[str, Any]:
    """Parse raw Avito webhook data into normalized payload.

    Args:
        raw: Raw HTTP body bytes.

    Returns:
        Normalized payload dictionary suitable for `_process_incoming`.

    Raises:
        ValueError: If the JSON is malformed or required identifiers are missing.
    """
    try:
        data = json.loads(raw.decode() or "{}")
    except Exception as exc:  # pragma: no cover - log only
        logger.warning("Avito payload parse error: %s", exc)
        raise ValueError("invalid json") from exc

    payload_root = data.get("payload") or {}
    val = payload_root.get("value") or {}

    chat_id = str(val.get("chat_id") or "")
    if not chat_id:
        raise ValueError("missing chat_id")

    text = (val.get("content") or {}).get("text") or ""
    item = val.get("item") or {}
    ctx = val.get("context") or {}

    item_id = str(item.get("id") or ctx.get("item_id") or "")
    vacancy_title = item.get("title") or val.get("title") or "Отклик Avito"
    vacancy_desc = item.get("description") or ctx.get("description") or ""
    applicant_id = str(val.get("user_id") or val.get("author_id") or "")

    owner_id = (
        str(
            data.get("account_id")
            or payload_root.get("account_id")
            or val.get("account_id")
            or ""
        )
        or None
    )

    return {
        "platform": "avito",
        "owner_id": owner_id,
        "vacancy_id": item_id,
        "vacancy_title": vacancy_title,
        "vacancy_desc": vacancy_desc,
        "applicant": {"id": chat_id, "name": f'user:{applicant_id or "unknown"}'},
        "raw_text": text,
    }


__all__ = ["parse_hh_payload", "parse_avito_payload"]
