"""Endpoints handling incoming HeadHunter webhooks."""

import logging
import httpx
from fastapi import APIRouter, Depends, Request

from app.adapters.amo_client import AmoClient
from app.http_client import get_http_client
from app.services.dedup import calc_key, check_and_store
from app.services.payload_parsers import parse_hh_payload
from app.services.lead_processor import (
    enrich_applicant,
    create_lead,
    send_invite,
    tag_lead,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/hh")
async def webhook_hh(
    request: Request, http_client: httpx.AsyncClient = Depends(get_http_client)
):
    raw = await request.body()

    key = calc_key("hh", raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}

    try:
        payload = parse_hh_payload(raw)
    except ValueError as exc:
        logger.warning("HH webhook: %s; payload=%s", exc, raw)
        return {"ok": True, "skipped": True}

    payload = await enrich_applicant(payload, http_client)

    amo = await AmoClient.create(http_client)
    lead_id, kind = await create_lead(payload, amo)

    if not lead_id:
        if kind == "ignore":
            return {"ok": True, "ignored": True, "reason": "no-keywords"}
        return {"ok": True, "queued": True, "reason": "reauth_required"}

    await send_invite(payload, lead_id)
    await tag_lead(lead_id, kind, amo)

    return {"ok": True, "lead_id": lead_id}


__all__ = ["router"]
