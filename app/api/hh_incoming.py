"""Endpoints handling incoming HeadHunter webhooks."""

import httpx
from fastapi import APIRouter, Depends, Request

from app.api._webhook_common import process_job_board_webhook
from app.http_client import get_http_client
from app.services.payload_parsers import parse_hh_payload

router = APIRouter()


@router.post("/webhooks/hh")
async def webhook_hh(
    request: Request, http_client: httpx.AsyncClient = Depends(get_http_client)
):
    raw = await request.body()
    return await process_job_board_webhook("hh", raw, http_client, parse_hh_payload)


__all__ = ["router"]
