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


@router.post("/webhooks/hh/{owner_id}")
async def webhook_hh(
    owner_id: str,
    request: Request,
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    """Handle HeadHunter webhook events.

    The ``owner_id`` is embedded into the webhook URL so that we don't need to
    perform extra lookups to determine the employer. If the parsed payload lacks
    ``owner_id``, the value from the URL is used.
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

    def _parser(b: bytes):
        p = parse_hh_payload(b)
        p.owner_id = p.owner_id or owner_id
        return p

    return await process_job_board_webhook("hh", raw, http_client, _parser)


__all__ = ["router"]
