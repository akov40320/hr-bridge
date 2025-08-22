import json
import logging

from pydantic import ValidationError

from app.models import Applicant, IncomingPayload, AvitoPayload

logger = logging.getLogger(__name__)


def parse_hh_payload(raw: bytes) -> IncomingPayload:
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

    vacancy_id = str(vacancy.get("id") or data.get("vacancy_id") or "") or None
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

    try:
        return IncomingPayload(
            platform="hh",
            owner_id=owner_id,
            vacancy_id=vacancy_id,
            vacancy_title=vacancy_title,
            vacancy_desc=vacancy_desc,
            applicant=Applicant(id=response_id, name=applicant_name),
        )
    except ValidationError as exc:
        raise exc


def extract_avito_payload(raw: bytes) -> AvitoPayload:
    """Extract raw Avito webhook data into :class:`AvitoPayload`."""

    try:
        data = json.loads(raw.decode() or "{}")
    except Exception as exc:  # pragma: no cover - log only
        logger.warning("Avito payload parse error: %s", exc)
        raise ValueError("invalid json") from exc

    payload_root = data.get("payload") or {}
    val = payload_root.get("value") or {}

    chat_id = str(val.get("chat_id") or "")
    text = (val.get("content") or {}).get("text") or ""
    item = val.get("item") or {}
    ctx = val.get("context") or {}

    item_id = str(item.get("id") or ctx.get("item_id") or "") or None
    item_title = item.get("title") or val.get("title") or "Отклик Avito"
    item_description = item.get("description") or ctx.get("description") or ""
    applicant_id = str(val.get("user_id") or val.get("author_id") or "") or None

    owner_id = (
        str(
            data.get("account_id")
            or payload_root.get("account_id")
            or val.get("account_id")
            or "",
        )
        or None
    )

    return AvitoPayload(
        chat_id=chat_id,
        item_id=item_id,
        item_title=item_title,
        item_description=item_description,
        applicant_id=applicant_id,
        text=text,
        owner_id=owner_id,
    )


def parse_avito_payload(payload: AvitoPayload) -> IncomingPayload:
    """Normalize :class:`AvitoPayload` into :class:`IncomingPayload`."""

    try:
        return IncomingPayload(
            platform="avito",
            owner_id=payload.owner_id,
            vacancy_id=payload.item_id,
            vacancy_title=payload.item_title,
            vacancy_desc=payload.item_description,
            applicant=Applicant(
                id=payload.chat_id, name=f"user:{payload.applicant_id or 'unknown'}"
            ),
            raw_text=payload.text,
        )
    except ValidationError as exc:
        raise exc


__all__ = ["parse_hh_payload", "extract_avito_payload", "parse_avito_payload"]

