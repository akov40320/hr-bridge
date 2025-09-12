"""Эндпоинты для обработки входящих вебхуков AmoCRM."""

from typing import Any, Mapping, cast
import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.adapters.amo_client import AmoClient
from app.core.config import get_settings
from app.http_client import get_http_client
from app.services.dedup import calc_key, check_and_store
from app.services.hh_mapping import get as hh_map_get, load as hh_map_load
from app.services.queue import RabbitMQClient, rabbitmq
from app.store import find_link
from .utils import (
    REFUSAL_TEXT_TO_HH,
    events_from_form,
    is_refusal_code,
    norm_reason,
    refusal_text,
)

logger = logging.getLogger(__name__)
router = APIRouter()


async def parse_status_events(request: Request) -> list[tuple[int, int]]:
    """Р’РѕР·РІСЂР°С‰Р°РµС‚ СЃРїРёСЃРѕРє РїР°СЂ (lead_id, status_id) РёР· РїРѕР»РµР·РЅРѕР№ РЅР°РіСЂСѓР·РєРё РІРµР±С…СѓРєР° Amo."""
    events: list[tuple[int, int]] = []
    data: Any | None = None
    ctype = request.headers.get("content-type", "")
    if "json" in ctype:
        try:
            data = await request.json()
        except json.JSONDecodeError as exc:
            body = (await request.body()).decode("utf-8", errors="replace")
            logger.warning(
                "РќРµ СѓРґР°Р»РѕСЃСЊ СЂР°Р·РѕР±СЂР°С‚СЊ РІРµР±С…СѓРє СЃС‚Р°С‚СѓСЃР° AmoCRM: %s; body=%s", exc, body[:200]
            )
    if data is not None:
        try:
            if isinstance(data, dict) and data.get("leads", {}).get("status"):
                for it in data["leads"]["status"]:
                    lead_id = int(it["id"])
                    status_id = int(it.get("new_status_id") or it.get("status_id"))
                    events.append((lead_id, status_id))
        except (KeyError, ValueError) as exc:
            body = (await request.body()).decode("utf-8", errors="replace")
            logger.warning(
                "РќРµ СѓРґР°Р»РѕСЃСЊ СЂР°Р·РѕР±СЂР°С‚СЊ РІРµР±С…СѓРє СЃС‚Р°С‚СѓСЃР° AmoCRM: %s; body=%s", exc, body[:200]
            )
            raise HTTPException(status_code=400, detail=f"Invalid payload: {exc}") from exc

    if not events:
        form = await request.form()
        # РџСЂРµРѕР±СЂР°Р·СѓРµРј FormData Рє СЃР»РѕРІР°СЂСЋ РІРёРґР° dict[str, str]
        data_map: Mapping[str, str] = {
            k: (v if isinstance(v, str) else getattr(v, "filename", str(v)))
            for k, v in form.multi_items()
        }
        events = events_from_form(cast(Mapping[str, str], data_map))
    return events


async def _fetch_refusal_reason(
    lead_id: int, client: httpx.AsyncClient, field_id: int
) -> str | None:
    """РџРѕР»СѓС‡Р°РµС‚ С‚РµРєСЃС‚ РїСЂРёС‡РёРЅС‹ РѕС‚РєР°Р·Р° РґР»СЏ СѓРєР°Р·Р°РЅРЅРѕРіРѕ Р»РёРґР°."""
    try:
        amo = await AmoClient.create(client)
        lead = await amo.get_lead(lead_id)
    except httpx.HTTPError as exc:  # pragma: no cover - network failure
        logger.exception("РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ Р»РёРґ %s: %s", lead_id, exc)
        return None

    cfv = lead.get("custom_fields_values") or []
    field = next(
        (f for f in cfv if int(f.get("field_id") or 0) == int(field_id)),
        None,
    )
    if not field:
        return ""
    values = field.get("values") or []
    if not values:
        return ""
    value = values[0].get("value")
    if isinstance(value, dict):
        return value.get("value") or value.get("text") or ""
    return value or ""


async def handle_hh_event(
    lead_id: int,
    status_id: int,
    link: dict[str, Any],
    http_client: httpx.AsyncClient,
    queue_client: RabbitMQClient = rabbitmq,
) -> None:
    """РћР±РЅРѕРІР»СЏРµС‚ СЃРѕСЃС‚РѕСЏРЅРёРµ РІ HH РЅР° РѕСЃРЅРѕРІРµ РёР·РјРµРЅРµРЅРёСЏ СЃС‚Р°С‚СѓСЃР° РІ AmoCRM."""
    s = get_settings()
    ext_id = link.get("external_id")
    owner_id = link.get("owner_id")
    state = await hh_map_get(status_id)
    if state is None:
        await queue_client.publish_task({"platform": "system", "action": "hh_autofill"})
        logger.info("РќРµРёР·РІРµСЃС‚РЅС‹Р№ СЃС‚Р°С‚СѓСЃ Amo %s вЂ” РїРѕСЃС‚Р°РІР»РµРЅР° Р·Р°РґР°С‡Р° hh_autofill", status_id)
        return
    if not ext_id:
        return

    final_state = state
    if is_refusal_code(state) and s.AMO_CF_REFUSAL_REASON_ID:
        reason_text = await _fetch_refusal_reason(
            lead_id, http_client, s.AMO_CF_REFUSAL_REASON_ID
        )
        if reason_text is not None:
            mapped = REFUSAL_TEXT_TO_HH.get(norm_reason(reason_text))
            if mapped:
                final_state = mapped
            elif not reason_text.strip():
                try:
                    pretty = refusal_text(state) or state
                    amo = await AmoClient.create(http_client)
                    await amo.update_lead_custom_fields(
                        lead_id, {s.AMO_CF_REFUSAL_REASON_ID: pretty}
                    )
                except httpx.HTTPError:
                    logger.warning("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРєРѕРїРёСЂРѕРІР°С‚СЊ С‚РµРєСЃС‚ РїСЂРёС‡РёРЅС‹ РѕС‚РєР°Р·Р°")

    await queue_client.publish_task(
        {
            "platform": "hh",
            "action": "set_state",
            "external_id": ext_id,
            "target_state": final_state,
            "owner_id": owner_id,
        }
    )


async def handle_avito_event(
    _lead_id: int,
    _status_id: int,
    link: dict[str, Any],
    queue_client: RabbitMQClient = rabbitmq,
) -> None:
    """РџРѕРјРµС‡Р°РµС‚ РїРµСЂРµРїРёСЃРєСѓ Avito РєР°Рє РїСЂРѕС‡РёС‚Р°РЅРЅСѓСЋ РґР»СЏ РґР°РЅРЅРѕРіРѕ Р»РёРґР°."""
    ext_id = link.get("external_id")
    owner_id = link.get("owner_id")
    await queue_client.publish_task(
        {
            "platform": "avito",
            "action": "mark_read",
            "external_id": ext_id,
            "owner_id": owner_id,
        }
    )


@router.post("/webhooks/amo")
async def amo_webhook(
    request: Request,
    http_client: httpx.AsyncClient = Depends(get_http_client),
    queue_client: RabbitMQClient = Depends(lambda: rabbitmq),
):
    """РћР±СЂР°Р±Р°С‚С‹РІР°РµС‚ РІРµР±С…СѓРє AmoCRM Рё СЃРёРЅС…СЂРѕРЅРёР·РёСЂСѓРµС‚ СЃС‚Р°С‚СѓСЃС‹ Р»РёРґР° РІРѕ РІРЅРµС€РЅРёРµ РїР»Р°С‚С„РѕСЂРјС‹."""
    raw = await request.body()
    key = calc_key("amo", raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}

    await hh_map_load()
    events = await parse_status_events(request)

    for lead_id, status_id in events:
        link = await find_link(lead_id)
        if not link:
            logger.warning("РќР•Рў РЎР’РЇР—Р Р”Р›РЇ Р›РР”Рђ %s", lead_id)
            continue

        platform = link.get("platform")
        if platform == "hh":
            await handle_hh_event(lead_id, status_id, link, http_client, queue_client)
        elif platform == "avito":
            await handle_avito_event(lead_id, status_id, link, queue_client)

    return {"ok": True, "events": len(events)}


__all__ = ["router", "parse_status_events"]
