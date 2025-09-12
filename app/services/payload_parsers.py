"""Utilities for parsing webhook payloads from external job platforms."""
# pylint: disable=line-too-long

import json
import logging

from pydantic import ValidationError
from urllib.parse import parse_qs

from app.models import Applicant, IncomingPayload, AvitoPayload

logger = logging.getLogger(__name__)


def parse_hh_payload(raw: bytes, owner_id: str | None = None) -> IncomingPayload:  # pylint: disable=too-many-locals
    """Parse HeadHunter webhook payload into an IncomingPayload."""

    try:
        data = json.loads(raw.decode() or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("HH payload parse error: %s", exc)
        raise ValueError("invalid HH payload") from exc

    action_type = str(data.get("action_type") or "").strip()
    if action_type and action_type != "NEW_NEGOTIATION_VACANCY":
        raise ValueError(f"unsupported action_type: {action_type}")

    obj = (
        data.get("object")
        or data.get("negotiation")
        or data.get("response")
        or data.get("payload")
        or {}
    )

    negotiation_id = str(
        obj.get("topic_id")
        or obj.get("id")
        or obj.get("negotiation_id")
        or data.get("response_id")
        or ""
    ).strip() or None

    if not negotiation_id:
        # лучше уронить с понятной ошибкой, чем продолжить с chat_id/resume_id
        raise ValueError("missing negotiation_id (topic_id) in HH payload")

    vacancy = obj.get("vacancy") or {}
    applicant = obj.get("applicant") or obj.get("resume", {}).get("owner", {}) or {}

    vacancy_id = str(
        vacancy.get("id")
        or data.get("vacancy_id")
        or obj.get("vacancy_id")
        or ""
    ).strip() or None

    vacancy_title = vacancy.get("name") or data.get("vacancy_title") or ""
    vacancy_desc = vacancy.get("description") or data.get("vacancy_description") or ""
    applicant_name = (applicant.get("name") or applicant.get("first_name") or "").strip() or "кандидат"

    parsed_owner_id = str(
        data.get("employer", {}).get("id")
        or obj.get("employer", {}).get("id")
        or obj.get("employer_id")
        or ""
    ).strip() or None

    # Лог для контроля
    logger.info("hh: parsed nid=%s vacancy_id=%s", negotiation_id, vacancy_id)

    return IncomingPayload(
        platform="hh",
        owner_id=owner_id or parsed_owner_id,
        vacancy_id=vacancy_id,
        vacancy_title=vacancy_title,
        vacancy_desc=vacancy_desc,
        applicant=Applicant(id=negotiation_id, name=applicant_name),
    )


def extract_avito_payload(raw: bytes) -> AvitoPayload:  # pylint: disable=too-many-locals,too-many-statements
    """Extract Avito payload from JSON or form-encoded body."""
    # 1) Безопасно декодируем тело
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        logger.warning("Avito payload decode error: %s", exc)
        raise ValueError("invalid Avito payload encoding") from exc

    # 2) Пытаемся распарсить как JSON, иначе — как форму payload=<json>
    data = None
    try:
        data = json.loads(body or "{}")
    except json.JSONDecodeError as json_exc:
        logger.warning("Avito payload JSON decode error: %s", json_exc)
        form = parse_qs(body)
        if "payload" in form and form["payload"]:
            try:
                data = json.loads(form["payload"][0])
            except json.JSONDecodeError as form_exc:
                logger.warning("Avito form payload parse error: %s", form_exc)
                raise ValueError("invalid Avito payload JSON") from form_exc
        else:
            raise ValueError("missing payload field in Avito form") from json_exc
    if not isinstance(data, dict):
        raise ValueError("invalid Avito payload: not a JSON object")

    # ---------- ВЕБХУК МЕССЕНДЖЕРА ----------
    # ожидается структура: {"payload":{"type": "...", "value": {...}}}
    payload_root = data.get("payload")
    if isinstance(payload_root, dict) and (
        "value" in payload_root or "type" in payload_root
    ):
        val = payload_root.get("value") or {}

        chat_id = str(val.get("chat_id") or "") or None
        if not chat_id:
            # резервный вариант: иногда чат кладут сюда
            chat_id = str(
                data.get("contacts", {}).get("chat", {}).get("value") or ""
            ) or None

        content = val.get("content") or {}
        text = content.get("text") or ""

        item = val.get("item") or {}
        ctx = val.get("context") or {}
        ctx_val = (ctx.get("value") or {}) if isinstance(ctx, dict) else {}

        item_id = (
                          str(item.get("id") or "") or
                          str(ctx_val.get("id") or "") or
                          str((ctx.get("id") if isinstance(ctx, dict) else "") or "") or
                          str((ctx.get("item_id") if isinstance(ctx, dict) else "") or "")
                  ) or None

        item_title = (
                item.get("title")
                or ctx_val.get("title")
                or val.get("title")
                or "Отклик Avito"
        )
        item_description = (
                item.get("description")
                or ctx_val.get("description")
                or (ctx.get("description") if isinstance(ctx, dict) else "")
                or ""
        )

        applicant_id = str(val.get("author_id") or val.get("user_id") or "") or None
        owner_id = str(
            data.get("account_id")
            or payload_root.get("account_id")
            or val.get("account_id")
            or ""
        ) or None

        return AvitoPayload(
            chat_id=chat_id,
            item_id=item_id,
            item_title=item_title,
            item_description=item_description,
            applicant_id=applicant_id,
            text=text,
            owner_id=owner_id,
        )

    # ---------- ВЕБХУК ОТКЛИКОВ (APPLICATIONS) ----------
    # ожидается структура: {"event":"application.created", "application": {...}}
    application = data.get("application") if isinstance(data.get("application"), dict) else None
    event = str(data.get("event") or "") or ""

    if application or event.startswith("application."):
        app_id = str((application or {}).get("id") or "") or None
        if not app_id:
            raise ValueError("missing application.id in Avito applications payload")

        # синтетический канал, чтобы не рушить общий конвейер
        chat_id = f"app:{app_id}"

        item_id = str((application or {}).get("vacancy_id") or "") or None
        applicant_id = str(
            (application or {}).get("resume_id")
            or (application or {}).get("applicant_id")
            or ""
        ) or None

        # минимальные текст/заголовок для карточки
        item_title = "Отклик по вакансии"
        item_description = ""
        state_or_status = (application or {}).get("state") or (application or {}).get("status")
        text = (event or "application.event") + (f": {state_or_status}" if state_or_status else "")

        owner_id = str(
            data.get("account_id")
            or (application or {}).get("account_id")
            or ""
        ) or None

        return AvitoPayload(
            chat_id=chat_id,
            item_id=item_id,
            item_title=item_title,
            item_description=item_description,
            applicant_id=applicant_id,
            text=text,
            owner_id=owner_id,
        )

    # ---------- ЛЕГАСИ-ФОЛБЭК (если прилетел минималистичный формат) ----------
    chat_id = str(
        data.get("contacts", {}).get("chat", {}).get("value") or ""
    ) or None
    if not chat_id:
        raise ValueError("unrecognized Avito payload format (no payload/type, no application, no contacts.chat)")

    return AvitoPayload(
        chat_id=chat_id,
        item_id=None,
        item_title="Отклик Avito",
        item_description="",
        applicant_id=None,
        text="",
        owner_id=str(data.get("account_id") or "") or None,
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
