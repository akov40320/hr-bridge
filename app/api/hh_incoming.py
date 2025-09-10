"""Endpoints handling incoming HeadHunter webhooks."""

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

    Fetches the raw request body and passes it to the generic job board
    webhook processor along with the HeadHunter payload parser.
    """
    raw = await request.body()
    try:
        log.info("HH webhook received raw: %s", raw.decode("utf-8"))
    except Exception:
        log.info("HH webhook received raw (binary): %s", raw)
    return await process_job_board_webhook(
        "hh", raw, http_client, lambda raw: parse_hh_payload(raw, owner_id)
    )


__all__ = ["router"]
