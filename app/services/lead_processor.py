"""Service utilities for handling leads and applicants."""

import json
import logging
import time

import httpx

from app.adapters import hh as hh_adapt
from app.adapters.amo_client import ReauthRequired
from app.core.config import get_settings
from app.services.queue import rabbitmq, RabbitMQClient
from app.store import save_link
from app.services import amo_lead_enrichment
from app.models import IncomingPayload

logger = logging.getLogger(__name__)


async def enrich_applicant(
    payload: IncomingPayload, http_client: httpx.AsyncClient
) -> IncomingPayload:
    """Enrich applicant data from HeadHunter if possible."""
    owner_id = payload.owner_id
    if payload.platform == "hh" and payload.applicant.id:
        try:
            extra = await hh_adapt.fetch_applicant_details(
                payload.applicant.id, owner_id, http_client
            )
            if extra:
                payload.applicant.phone = payload.applicant.phone or extra.get("phone")
                payload.applicant.city = payload.applicant.city or extra.get("city")
                payload.applicant.email = payload.applicant.email or extra.get("email")
                payload.applicant.name = (
                    payload.applicant.name
                    if payload.applicant.name and payload.applicant.name != "кандидат"
                    else extra.get("name") or payload.applicant.name
                )
        except (httpx.HTTPError, json.JSONDecodeError) as e:  # pragma: no cover - log only
            logger.warning(
                "HH enrich failed for applicant %s: %s",
                payload.applicant.id,
                type(e).__name__,
            )
    if (
        payload.platform == "hh"
        and not payload.vacancy_desc
        and payload.vacancy_id
    ):
        try:
            desc = await hh_adapt.fetch_vacancy_description(
                payload.vacancy_id, owner_id, http_client
            )
            if desc:
                payload.vacancy_desc = desc
        except (httpx.HTTPError, json.JSONDecodeError) as e:  # pragma: no cover - log only
            logger.warning(
                "HH vacancy fetch failed for vacancy %s: %s",
                payload.vacancy_id,
                type(e).__name__,
            )
    return payload


async def create_lead(
    payload: IncomingPayload,
    client,
    queue_client: RabbitMQClient = rabbitmq,
) -> tuple[int | None, str]:
    """Create lead in AmoCRM and return (lead_id, kind)."""
    s = get_settings()
    from app.api.utils import route_kind

    kind = route_kind(
        desc=payload.vacancy_desc or "",
        raw=payload.raw_text or "",
    )
    payload.kind = kind

    if kind == "ignore":
        logger.info(
            "routing: ignore (no hashtags) title=%r",
            payload.vacancy_title or "",
        )
        return None, kind

    if kind == "master":
        pipeline_id = s.AMO_PIPELINE_ID_MASTER
        stage_id = s.AMO_STAGE_ID_MASTER_NEW
    else:
        pipeline_id = s.AMO_PIPELINE_ID_OPERATOR
        stage_id = s.AMO_STAGE_ID_OPERATOR_NEW

    lead_name = (
        f"{payload.vacancy_title or ''} — {payload.applicant.name or 'кандидат'}"
    ).strip(" —")

    logger.info(
        "lead:create platform=%s -> name=%s pipeline=%s stage=%s",
        payload.platform,
        lead_name,
        pipeline_id,
        stage_id,
    )

    body = [{"name": lead_name, "pipeline_id": pipeline_id, "status_id": stage_id}]
    try:
        created = await client.create_leads(body)
    except ReauthRequired:
        await queue_client.publish_task(
            {
                "platform": payload.platform or "unknown",
                "action": "amo_create_lead",
                "lead_body": body,
                "ts": int(time.time()),
            }
        )
        return None, kind

    lead_id = created["_embedded"]["leads"][0]["id"]

    await amo_lead_enrichment.enrich_lead(
        client,
        lead_id,
        applicant_name=payload.applicant.name,
        phone=payload.applicant.phone,
        city=payload.applicant.city,
        vacancy_title=payload.vacancy_title,
        email=payload.applicant.email,
    )

    await save_link(
        lead_id=lead_id,
        platform=payload.platform or "unknown",
        owner_id=payload.owner_id,
        vacancy_id=str(payload.vacancy_id or ""),
        external_id=str(payload.applicant.id or "") or None,
    )

    return lead_id, kind


async def send_invite(
    payload: IncomingPayload, lead_id: int, queue_client: RabbitMQClient = rabbitmq
) -> str:
    """Send invite link to applicant via platform-specific channels."""
    s = get_settings()
    from app.api.utils import route_kind

    kind = payload.kind or route_kind(
        desc=payload.vacancy_desc or "",
        raw=payload.raw_text or "",
    )
    bot_username = (
        s.TELEGRAM_MASTER_BOT_USERNAME
        if kind == "master"
        else s.TELEGRAM_OPERATOR_BOT_USERNAME
    )
    deep_link = f"https://t.me/{bot_username}?start={lead_id}"
    invite_text = (
        "Здравствуйте! Перейдите, пожалуйста, в Telegram-бот и пройдите короткий опрос:"
        f" {deep_link}"
    )

    platform = payload.platform
    applicant_id = payload.applicant.id
    if platform == "avito" and applicant_id:
        await queue_client.publish_task(
            {
                "platform": "avito",
                "action": "send_message",
                "external_id": applicant_id,
                "text": invite_text,
                "owner_id": payload.owner_id,
            }
        )
    if platform == "hh" and applicant_id:
        await queue_client.publish_task(
            {
                "platform": "hh",
                "action": "send_message",
                "external_id": applicant_id,
                "text": invite_text,
                "owner_id": payload.owner_id,
            }
        )
    return deep_link


async def tag_lead(lead_id: int, kind: str, amo_client) -> None:
    """Apply tags to the created lead."""
    await amo_client.add_tags(
        lead_id,
        [f"type:{'мастер' if kind == 'master' else 'оператор'}"],
    )


__all__ = [
    "enrich_applicant",
    "create_lead",
    "send_invite",
    "tag_lead",
]
