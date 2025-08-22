"""Endpoints handling incoming HeadHunter webhooks."""

import logging
import httpx
from fastapi import APIRouter, Depends, Request

from app.http_client import get_http_client
from app.services.dedup import calc_key, check_and_store

from .webhooks import _process_incoming

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/hh")
async def webhook_hh(
    request: Request, http_client: httpx.AsyncClient = Depends(get_http_client)
):
    raw = await request.body()
    try:
        data = await request.json()
    except Exception:
        data = {}

    key = calc_key("hh", raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}

    obj = (
        data.get("object")
        or data.get("negotiation")
        or data.get("response")
        or data.get("payload")
        or {}
    )

    response_id = str(
        obj.get("id")
        or data.get("response_id")
        or obj.get("negotiation_id")
        or ""
    )

    vacancy = obj.get("vacancy") or {}
    applicant = (obj.get("applicant") or obj.get("resume", {}).get("owner", {}) or {})

    vacancy_id = str(vacancy.get("id") or data.get("vacancy_id") or "")
    vacancy_title = vacancy.get("name") or data.get("vacancy_title") or ""
    vacancy_desc = vacancy.get("description") or data.get("vacancy_description") or ""
    applicant_name = (
        applicant.get("name") or applicant.get("first_name") or ""
    ).strip() or "кандидат"

    owner_id = str(
        data.get("employer", {}).get("id")
        or obj.get("employer", {}).get("id")
        or ""
    ) or None

    if not response_id:
        logger.warning("HH webhook: no response_id; payload=%s", data)
        return {"ok": True, "skipped": True}

    payload = {
        "platform": "hh",
        "owner_id": owner_id,
        "vacancy_id": vacancy_id,
        "vacancy_title": vacancy_title,
        "vacancy_desc": vacancy_desc,
        "applicant": {"id": response_id, "name": applicant_name},
    }
    return await _process_incoming(payload, http_client)


__all__ = ["router"]
