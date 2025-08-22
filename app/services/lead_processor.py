import logging
import time
import httpx
import json

from app.adapters import hh as hh_adapt
from app.adapters.amo_client import ReauthRequired
from app.core.config import settings
from app.services.queue import publish_task
from app.store import save_link
from app.api.utils import route_kind
from app.services import amo_lead_enrichment
from app.models import IncomingPayload

logger = logging.getLogger(__name__)


async def enrich_applicant(
    payload: IncomingPayload, http_client: httpx.AsyncClient
) -> IncomingPayload:
    """Enrich applicant data from HeadHunter if possible."""
    if payload.platform == "hh" and payload.applicant.id:
        owner_id = payload.owner_id
        try:
            extra = await hh_adapt.fetch_applicant_details(
                payload.applicant.id, owner_id, http_client
            )
            if extra:
                payload.applicant.phone = payload.applicant.phone or extra.get("phone")
                payload.applicant.city = payload.applicant.city or extra.get("city")
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
    return payload


async def create_lead(payload: IncomingPayload, client) -> tuple[int | None, str]:
    """Create lead in AmoCRM and return (lead_id, kind)."""
    title = payload.vacancy_title or ""
    desc = payload.vacancy_desc or ""
    raw = payload.raw_text or ""
    kind = route_kind(desc=desc, raw=raw)
    payload.kind = kind

    phone = payload.applicant.phone
    city = payload.applicant.city
    name = payload.applicant.name

    if kind == "ignore":
        logger.info("routing: ignore (no hashtags) title=%r", title)
        return None, kind

    if kind == "master":
        pipeline_id = settings.AMO_PIPELINE_ID_MASTER
        stage_id = settings.AMO_STAGE_ID_MASTER_NEW
    else:
        pipeline_id = settings.AMO_PIPELINE_ID_OPERATOR
        stage_id = settings.AMO_STAGE_ID_OPERATOR_NEW

    lead_name = f"{title} — {name or 'кандидат'}".strip(" —")

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
        await publish_task(
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
        applicant_name=name,
        phone=phone,
        city=city,
        vacancy_title=payload.vacancy_title,
    )

    await save_link(
        lead_id=lead_id,
        platform=payload.platform or "unknown",
        owner_id=payload.owner_id,
        vacancy_id=str(payload.vacancy_id or ""),
        external_id=str(payload.applicant.id or "") or None,
    )

    return lead_id, kind


async def send_invite(payload: IncomingPayload, lead_id: int) -> str:
    """Send invite link to applicant via platform-specific channels."""
    kind = payload.kind or route_kind(
        desc=payload.vacancy_desc or "",
        raw=payload.raw_text or "",
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

    platform = payload.platform
    applicant_id = payload.applicant.id
    if platform == "avito" and applicant_id:
        await publish_task(
            {
                "platform": "avito",
                "action": "send_message",
                "external_id": applicant_id,
                "text": invite_text,
                "owner_id": payload.owner_id,
            }
        )
    if platform == "hh" and applicant_id:
        await publish_task(
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
