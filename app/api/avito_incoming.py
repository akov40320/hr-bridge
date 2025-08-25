"""Endpoints handling incoming Avito webhooks."""

import logging
import httpx
from fastapi import APIRouter, Depends, Request

from app.api._webhook_common import process_job_board_webhook
from app.http_client import get_http_client
from app.services.payload_parsers import extract_avito_payload, parse_avito_payload

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/avito")
async def webhook_avito(
    request: Request, http_client: httpx.AsyncClient = Depends(get_http_client)
):
    """Handle incoming Avito webhook requests."""
    raw = await request.body()

    logger.info("Received Avito webhook with payload size %d", len(raw))

    def parse(raw_bytes: bytes):
        return parse_avito_payload(extract_avito_payload(raw_bytes))

    return await process_job_board_webhook("avito", raw, http_client, parse)


__all__ = ["router"]
