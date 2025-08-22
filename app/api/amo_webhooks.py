"""Endpoints handling incoming AmoCRM webhooks."""

import logging
import httpx
from fastapi import APIRouter, Depends, Request

from app.adapters.amo_client import AmoClient
from app.core.config import settings
from app.http_client import get_http_client
from app.services.dedup import calc_key, check_and_store
from app.services.hh_mapping import get as hh_map_get, load as hh_map_load
from app.services.queue import publish_task
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


@router.post("/webhooks/amo")
async def amo_webhook(
    request: Request, http_client: httpx.AsyncClient = Depends(get_http_client)
):
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
