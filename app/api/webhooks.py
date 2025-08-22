"""Shared utilities for processing incoming webhooks."""

import logging
import time
import httpx

from app.adapters import hh as hh_adapt
from app.adapters.amo_client import AmoClient, ReauthRequired
from app.core.config import settings
from app.services.queue import publish_task
from app.store import save_link

from .utils import route_kind

logger = logging.getLogger(__name__)


async def _process_incoming(payload: dict, http_client: httpx.AsyncClient):
    """Create a lead in AmoCRM from an incoming webhook payload."""
    title = payload.get("vacancy_title") or ""
    desc = payload.get("vacancy_desc") or ""
    raw = payload.get("raw_text") or ""
    kind = route_kind(desc=desc, raw=raw)
    phone = (payload.get("applicant", {}) or {}).get("phone")
    city = (payload.get("applicant", {}) or {}).get("city")
    name = (payload.get("applicant", {}) or {}).get("name")
    owner_id = payload.get("owner_id")

    if payload.get("platform") == "hh" and payload.get("applicant", {}).get("id"):
        try:
            extra = await hh_adapt.fetch_applicant_details(
                payload["applicant"]["id"], owner_id, http_client
            )
            if extra:
                phone = phone or extra.get("phone")
                city = city or extra.get("city")
                name = (
                    name if name and name != "кандидат" else (extra.get("name") or name)
                )
        except Exception as e:  # pragma: no cover - log only
            logger.warning("HH enrich failed: %s", e)

    if kind == "ignore":
        logger.info("routing: ignore (no hashtags) title=%r", title)
        return {"ok": True, "ignored": True, "reason": "no-keywords"}

    amo = await AmoClient.create(http_client)

    if kind == "master":
        pipeline_id = settings.AMO_PIPELINE_ID_MASTER
        stage_id = settings.AMO_STAGE_ID_MASTER_NEW
    else:
        pipeline_id = settings.AMO_PIPELINE_ID_OPERATOR
        stage_id = settings.AMO_STAGE_ID_OPERATOR_NEW

    lead_name = f"{title} — {name or 'кандидат'}".strip(" —")

    logger.info(
        "lead:create platform=%s -> name=%s pipeline=%s stage=%s",
        payload.get("platform"),
        lead_name,
        pipeline_id,
        stage_id,
    )

    body = [{"name": lead_name, "pipeline_id": pipeline_id, "status_id": stage_id}]
    try:
        created = await amo.create_leads(body)
    except ReauthRequired:
        await publish_task(
            {
                "platform": payload.get("platform", "unknown"),
                "action": "amo_create_lead",
                "lead_body": body,
                "ts": int(time.time()),
            }
        )
        return {"ok": True, "queued": True, "reason": "reauth_required"}

    lead_id = created["_embedded"]["leads"][0]["id"]

    await _enrich_lead(
        amo,
        lead_id,
        applicant_name=name,
        phone=phone,
        city=city,
        vacancy_title=payload.get("vacancy_title"),
    )

    logger.info(
        "lead:created id=%s platform=%s vac=%s ext=%s",
        lead_id,
        payload.get("platform"),
        payload.get("vacancy_id"),
        payload.get("applicant", {}).get("id"),
    )

    await save_link(
        lead_id=lead_id,
        platform=payload.get("platform", "unknown"),
        owner_id=payload.get("owner_id"),
        vacancy_id=str(payload.get("vacancy_id", "")),
        external_id=str(payload.get("applicant", {}).get("id") or "") or None,
    )

    bot_username = (
        settings.TELEGRAM_MASTER_BOT_USERNAME
        if kind == "master"
        else settings.TELEGRAM_OPERATOR_BOT_USERNAME
    )
    deep_link = f"https://t.me/{bot_username}?start={lead_id}"
    invite_text = (
        "Здравствуйте! Перейдите, пожалуйста, в Telegram-бот и пройдите короткий опрос:"
        f" {deep_link}"
    )

    if payload.get("platform") == "avito" and payload.get("applicant", {}).get("id"):
        await publish_task(
            {
                "platform": "avito",
                "action": "send_message",
                "external_id": payload["applicant"]["id"],
                "text": invite_text,
                "owner_id": payload.get("owner_id"),
            }
        )

    if payload.get("platform") == "hh" and payload.get("applicant", {}).get("id"):
        await publish_task(
            {
                "platform": "hh",
                "action": "send_message",
                "external_id": payload["applicant"]["id"],
                "text": invite_text,
                "owner_id": payload.get("owner_id"),
            }
        )

    await amo.add_tags(
        lead_id,
        [
            f"source:{payload.get('platform', '') or 'unknown'}",
            f"type:{'мастер' if kind == 'master' else 'оператор'}",
        ],
    )

    try:
        await amo.add_note(lead_id, f"Отправлена ссылка на TG-бота: {deep_link}")
    except Exception as e:  # pragma: no cover - log only
        logger.warning("add note (link sent) error: %s", e)

    return {"ok": True, "lead_id": lead_id}


async def _enrich_lead(
    amo: AmoClient,
    lead_id: int,
    *,
    applicant_name: str | None,
    phone: str | None,
    city: str | None,
    vacancy_title: str | None,
):
    """Attach extra data to a newly created lead."""
    contact_id = None
    if applicant_name or phone:
        try:
            cr = await amo.create_contact(applicant_name or "Кандидат", phone)
            contact_id = cr["_embedded"]["contacts"][0]["id"]
            await amo.link_contact_to_lead(lead_id, contact_id)
        except Exception as e:  # pragma: no cover - log only
            logger.warning("create/link contact failed: %s", e)

    cf: dict[int, str] = {}
    if settings.AMO_CF_LEAD_CITY_ID:
        cf[settings.AMO_CF_LEAD_CITY_ID] = city or ""
    if settings.AMO_CF_LEAD_VACANCY_TITLE_ID:
        cf[settings.AMO_CF_LEAD_VACANCY_TITLE_ID] = vacancy_title or ""
    if settings.AMO_CF_LEAD_APPLICANT_PHONE_ID:
        cf[settings.AMO_CF_LEAD_APPLICANT_PHONE_ID] = phone or ""
    if settings.AMO_CF_LEAD_APPLICANT_NAME_ID:
        cf[settings.AMO_CF_LEAD_APPLICANT_NAME_ID] = applicant_name or ""
    try:
        await amo.update_lead_custom_fields(lead_id, cf)
    except Exception as e:  # pragma: no cover - log only
        logger.warning("update lead CF failed: %s", e)

    if not any(
        [
            settings.AMO_CF_LEAD_CITY_ID,
            settings.AMO_CF_LEAD_VACANCY_TITLE_ID,
            settings.AMO_CF_LEAD_APPLICANT_PHONE_ID,
            settings.AMO_CF_LEAD_APPLICANT_NAME_ID,
        ]
    ):
        try:
            note = (
                "Данные кандидата:\n"
                f"• Имя: {applicant_name or '-'}\n"
                f"• Телефон: {phone or '-'}\n"
                f"• Город: {city or '-'}\n"
                f"• Вакансия: {vacancy_title or '-'}"
            )
            await amo.add_note(lead_id, note)
        except Exception as e:  # pragma: no cover - log only
            logger.warning("add note (candidate data) error: %s", e)


__all__ = ["_process_incoming", "_enrich_lead"]
