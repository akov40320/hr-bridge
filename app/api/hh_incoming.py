"""Endpoints handling incoming HeadHunter webhooks."""

import logging
import httpx
from fastapi import APIRouter, Depends, Request

from app.http_client import get_http_client
from app.services.dedup import calc_key, check_and_store
from app.services.payload_parsers import parse_hh_payload

from .webhooks import _process_incoming

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

    return await _process_incoming(payload, http_client)


__all__ = ["router"]
