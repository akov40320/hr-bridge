"""FastAPI endpoint for incoming Avito webhooks with signature verification."""

import os
import hmac
import hashlib
import time
import logging

import httpx
from fastapi import APIRouter, Depends, Request, HTTPException

from app.api._webhook_common import process_job_board_webhook
from app.http_client import get_http_client
from app.services.payload_parsers import extract_avito_payload, parse_avito_payload

router = APIRouter()
_AVITO_SECRET = os.getenv("AVITO_WEBHOOK_SECRET", "").strip()
_SIG_HEADER = os.getenv("AVITO_SIGNATURE_HEADER", "X-Avito-Signature")

logger = logging.getLogger(__name__)


def _verify_sig(raw: bytes, sent_sig: str | None) -> None:
    if not _AVITO_SECRET:
        return
    if not sent_sig:
        raise HTTPException(status_code=401, detail="Missing signature")
    # Signature is HMAC-SHA256 in hex; header may be prefixed with 'sha256='
    if sent_sig.lower().startswith("sha256="):
        sent_sig = sent_sig[7:]
    calc = hmac.new(_AVITO_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, sent_sig):
        raise HTTPException(status_code=401, detail="Bad signature")


@router.post("/webhooks/avito")
async def webhook_avito(
    request: Request, http_client: httpx.AsyncClient = Depends(get_http_client)
):
    """Handle Avito webhook, verify signature, and dispatch processing."""
    t0 = time.monotonic()
    raw = await request.body()
    sig = request.headers.get(_SIG_HEADER)

    logger.info(
        "avito:webhook received len=%d sig_present=%s ua=%s",
        len(raw), bool(sig), request.headers.get("User-Agent")
    )

    _verify_sig(raw, sig)

    def parse(raw_bytes: bytes):
        return parse_avito_payload(extract_avito_payload(raw_bytes))

    resp = await process_job_board_webhook("avito", raw, http_client, parse)

    dt = (time.monotonic() - t0) * 1000
    try:
        p = parse_avito_payload(extract_avito_payload(raw))
        logger.info(
            "avito:webhook ok source=avito event=%s channel=%s vacancy=%s owner=%s dt=%.1fms",
            str(getattr(p, "raw_text", ""))[:32],
            p.applicant.id,
            p.vacancy_id,
            p.owner_id,
            dt,
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.info("avito:webhook ok (summary failed: %s) dt=%.1fms", e, dt)

    return resp
