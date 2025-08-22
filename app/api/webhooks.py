"""Endpoints handling external webhooks."""

import logging
import time
import httpx

from fastapi import APIRouter, Request, Depends

from app.adapters import avito as avito_adapt, hh as hh_adapt
from app.adapters.amo_client import AmoClient, ReauthRequired
from app.core.config import settings
from app.services.dedup import calc_key, check_and_store
from app.services.hh_mapping import get as hh_map_get, load as hh_map_load
from app.services.queue import publish_task
from app.store import find_link, save_link
from app.http_client import get_http_client

from .utils import (
    REFUSAL_TEXT_TO_HH,
    events_from_form,
    is_refusal_code,
    norm_reason,
    refusal_text,
    route_kind,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/hh")
async def webhook_hh(request: Request, http_client: httpx.AsyncClient = Depends(get_http_client)):
    raw = await request.body()
    try:
        data = await request.json()
    except Exception:
        data = {}

    key = calc_key("hh", raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}

    obj = (
        data.get("object")
        or data.get("negotiation")
        or data.get("response")
        or data.get("payload")
        or {}
    )

    # response/negotiation id — КЛЮЧЕВОЕ
    response_id = str(
        obj.get("id")
        or data.get("response_id")
        or obj.get("negotiation_id")
        or ""
    )

    vacancy = obj.get("vacancy") or {}

    applicant = (obj.get("applicant") or obj.get("resume", {}).get("owner", {}) or {})

    vacancy_id = str(vacancy.get("id") or data.get("vacancy_id") or "")
    vacancy_title = (vacancy.get("name") or data.get("vacancy_title") or "")
    vacancy_desc = (vacancy.get("description") or data.get("vacancy_description") or "")
    applicant_name = (applicant.get("name") or applicant.get("first_name") or "").strip() or "кандидат"

    # employer_id (владалец токена)
    owner_id = str(
        data.get("employer", {}).get("id")
        or obj.get("employer", {}).get("id")
        or ""
    ) or None

    if not response_id:
        logger.warning("HH webhook: no response_id; payload=%s", data)
        return {"ok": True, "skipped": True}

    payload = {
        "platform": "hh",
        "owner_id": owner_id,
        "vacancy_id": vacancy_id,
        "vacancy_title": vacancy_title,
        "vacancy_desc": vacancy_desc,
        "applicant": {"id": response_id, "name": applicant_name},
    }
    return await _process_incoming(payload, http_client)


@router.post("/webhooks/avito")
async def webhook_avito(request: Request, http_client: httpx.AsyncClient = Depends(get_http_client)):
    raw = await request.body()
    try:
        data = await request.json()
    except Exception:
        data = {}

    key = calc_key("avito", raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}

    payload_root = data.get("payload") or {}
    val = payload_root.get("value") or {}

    chat_id = str(val.get("chat_id") or "")
    text = (val.get("content") or {}).get("text") or ""

    # Пытаемся вытащить ID и заголовок объявления
    item = val.get("item") or {}
    ctx = val.get("context") or {}
    item_id = str(item.get("id") or ctx.get("item_id") or "")
    vacancy_title = (item.get("title") or val.get("title") or "Отклик Avito")
    vacancy_desc = (item.get("description") or ctx.get("description") or "")

    applicant_id = str(val.get("user_id") or val.get("author_id") or "")

    owner_id = str(
        data.get("account_id")
        or payload_root.get("account_id")
        or val.get("account_id")
        or ""
    ) or None

    if not chat_id:
        logger.warning("Avito webhook: no chat_id, payload=%s", data)
        return {"ok": True, "skipped": True}

    internal = {
        "platform": "avito",
        "owner_id": owner_id,
        "vacancy_id": item_id,
        "vacancy_title": vacancy_title,
        "vacancy_desc": vacancy_desc,
        "applicant": {"id": chat_id, "name": f"user:{applicant_id or 'unknown'}"},
        "raw_text": text,
    }
    return await _process_incoming(internal, http_client)


async def _process_incoming(payload: dict, http_client: httpx.AsyncClient):
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
        except Exception as e:
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

    lead_name = f'{title} — {name or "кандидат"}'.strip(" —")

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
            f'source:{payload.get("platform", "") or "unknown"}',
            f'type:{"мастер" if kind == "master" else "оператор"}',
        ],
    )

    try:
        await amo.add_note(lead_id, f"Отправлена ссылка на TG-бота: {deep_link}")
    except Exception as e:
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
    contact_id = None
    if applicant_name or phone:
        try:
            cr = await amo.create_contact(applicant_name or "Кандидат", phone)
            contact_id = cr["_embedded"]["contacts"][0]["id"]
            await amo.link_contact_to_lead(lead_id, contact_id)
        except Exception as e:
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
    except Exception as e:
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
        except Exception as e:
            logger.warning("add note (candidate data) error: %s", e)


@router.post("/webhooks/amo")
async def amo_webhook(request: Request, http_client: httpx.AsyncClient = Depends(get_http_client)):
    raw = await request.body()
    key = calc_key("amo", raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}

    hh_map_load()
    events: list[tuple[int, int]] = []

    try:
        data = await request.json()
        if isinstance(data, dict) and data.get("leads", {}).get("status"):
            for it in data["leads"]["status"]:
                lead_id = int(it["id"])
                status_id = int(it.get("new_status_id") or it.get("status_id"))
                events.append((lead_id, status_id))
    except Exception:
        pass

    if not events:
        form = await request.form()
        events = events_from_form(form)

    for lead_id, status_id in events:
        link = await find_link(lead_id)
        if not link:
            logger.warning("NO LINK FOR LEAD %s", lead_id)
            continue

        platform = link.get("platform")
        ext_id = link.get("external_id")
        owner_id = link.get("owner_id")

        if platform == "hh":
            state = hh_map_get(status_id)
            if state and ext_id:
                final_state = state
                if is_refusal_code(state) and settings.AMO_CF_REFUSAL_REASON_ID:
                    try:
                        amo = await AmoClient.create(http_client)
                        lead = await amo.get_lead(lead_id)
                        cfv = lead.get("custom_fields_values") or []
                        reason_text = None
                        for f in cfv:
                            if int(f.get("field_id") or 0) == int(
                                settings.AMO_CF_REFUSAL_REASON_ID
                            ):
                                vals = f.get("values") or []
                                if vals:
                                    v = vals[0].get("value")
                                    if isinstance(v, dict):
                                        reason_text = v.get("value") or v.get("text") or ""
                                    else:
                                        reason_text = v or ""

                                break
                        mapped = REFUSAL_TEXT_TO_HH.get(norm_reason(reason_text))
                        if mapped:
                            final_state = mapped
                        elif reason_text is None or not reason_text.strip():
                            try:
                                pretty = refusal_text(state) or state
                                await amo.update_lead_custom_fields(
                                    lead_id,
                                    {settings.AMO_CF_REFUSAL_REASON_ID: pretty},
                                )
                            except Exception:
                                logger.warning("Failed to copy refusal text")
                    except Exception:
                        logger.exception("Failed to map refusal reason")
                await publish_task(
                    {
                        "platform": "hh",
                        "action": "set_state",
                        "external_id": ext_id,
                        "target_state": final_state,
                        "owner_id": owner_id,
                    }
                )
        if platform == "avito":
            await publish_task(
                {
                    "platform": "avito",
                    "action": "mark_read",
                    "external_id": ext_id,
                    "owner_id": owner_id,
                }
            )

    return {"ok": True, "events": len(events)}


__all__ = ["router"]

