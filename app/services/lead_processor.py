import logging
import time
import httpx

from app.adapters import hh as hh_adapt
from app.adapters.amo_client import ReauthRequired
from app.core.config import settings
from app.services.queue import publish_task
from app.store import save_link
from app.api.utils import route_kind

logger = logging.getLogger(__name__)


async def enrich_applicant(payload: dict, http_client: httpx.AsyncClient) -> dict:
    """Enrich applicant data from HeadHunter if possible."""
    if payload.get("platform") == "hh" and payload.get("applicant", {}).get("id"):
        owner_id = payload.get("owner_id")
        try:
            extra = await hh_adapt.fetch_applicant_details(
                payload["applicant"]["id"], owner_id, http_client
            )
            if extra:
                app = payload.setdefault("applicant", {})
                app["phone"] = app.get("phone") or extra.get("phone")
                app["city"] = app.get("city") or extra.get("city")
                app["name"] = (
                    app.get("name")
                    if app.get("name") and app.get("name") != "кандидат"
                    else extra.get("name") or app.get("name")
                )
        except Exception as e:  # pragma: no cover - log only
            logger.warning("HH enrich failed: %s", e)
    return payload


async def create_lead(payload: dict, client) -> tuple[int | None, str]:
    """Create lead in AmoCRM and return (lead_id, kind)."""
    title = payload.get("vacancy_title") or ""
    desc = payload.get("vacancy_desc") or ""
    raw = payload.get("raw_text") or ""
    kind = route_kind(desc=desc, raw=raw)
    payload["kind"] = kind

    phone = (payload.get("applicant", {}) or {}).get("phone")
    city = (payload.get("applicant", {}) or {}).get("city")
    name = (payload.get("applicant", {}) or {}).get("name")

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
        payload.get("platform"),
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
                "platform": payload.get("platform", "unknown"),
                "action": "amo_create_lead",
                "lead_body": body,
                "ts": int(time.time()),
            }
        )
        return None, kind

    lead_id = created["_embedded"]["leads"][0]["id"]

    await _enrich_lead(
        client,
        lead_id,
        applicant_name=name,
        phone=phone,
        city=city,
        vacancy_title=payload.get("vacancy_title"),
    )

    await save_link(
        lead_id=lead_id,
        platform=payload.get("platform", "unknown"),
        owner_id=payload.get("owner_id"),
        vacancy_id=str(payload.get("vacancy_id", "")),
        external_id=str(payload.get("applicant", {}).get("id") or "") or None,
    )

    return lead_id, kind


async def send_invite(payload: dict, lead_id: int) -> str:
    """Send invite link to applicant via platform-specific channels."""
    kind = payload.get("kind") or route_kind(
        desc=payload.get("vacancy_desc") or "",
        raw=payload.get("raw_text") or "",
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

    platform = payload.get("platform")
    applicant_id = (payload.get("applicant", {}) or {}).get("id")
    if platform == "avito" and applicant_id:
        await publish_task(
            {
                "platform": "avito",
                "action": "send_message",
                "external_id": applicant_id,
                "text": invite_text,
                "owner_id": payload.get("owner_id"),
            }
        )
    if platform == "hh" and applicant_id:
        await publish_task(
            {
                "platform": "hh",
                "action": "send_message",
                "external_id": applicant_id,
                "text": invite_text,
                "owner_id": payload.get("owner_id"),
            }
        )
    return deep_link


async def tag_lead(lead_id: int, kind: str, amo_client) -> None:
    """Apply tags to the created lead."""
    await amo_client.add_tags(
        lead_id,
        [f"type:{'мастер' if kind == 'master' else 'оператор'}"],
    )


async def _enrich_lead(
    amo,
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


__all__ = [
    "enrich_applicant",
    "create_lead",
    "send_invite",
    "tag_lead",
]
