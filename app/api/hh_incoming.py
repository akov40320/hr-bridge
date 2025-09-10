"""Endpoints handling incoming HeadHunter webhooks."""

import json
import logging

import httpx
from fastapi import APIRouter, Depends, Request

from app.api._webhook_common import process_job_board_webhook
from app.http_client import get_http_client
from app.services.payload_parsers import parse_hh_payload


router = APIRouter()
log = logging.getLogger(__name__)  


@router.post("/webhooks/hh")
async def webhook_hh(
    request: Request, http_client: httpx.AsyncClient = Depends(get_http_client)
):
    """Handle HeadHunter webhook events.

    Fetches the raw request body and passes it to the generic job board
    webhook processor along with the HeadHunter payload parser.
    """
    raw = await request.body()

    # Log a short summary at info level and keep the full body for debug logs.
    nid = None
    ts = None
    try:
        data = json.loads(raw.decode("utf-8", "ignore") or "{}")
        log.info(f"HH FULL WEBHOOK BODY: {data}") 
        obj = (
            data.get("object")
            or data.get("negotiation")
            or data.get("response")
            or data.get("payload")
            or {}
        )
        nid = (
            obj.get("topic_id")
            or obj.get("id")
            or obj.get("negotiation_id")
            or data.get("response_id")
        )
        ts = data.get("event_time") or data.get("timestamp")
    except Exception:
        pass
    log.info("HH webhook received nid=%s ts=%s", nid, ts)
    log.debug("HH webhook body: %s", raw.decode("utf-8", "ignore"))
    return await process_job_board_webhook("hh", raw, http_client, parse_hh_payload)


__all__ = ["router"]
