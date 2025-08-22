"""Endpoints handling incoming Avito webhooks."""

import logging
import httpx
from fastapi import APIRouter, Depends, Request

from app.http_client import get_http_client
from app.services.dedup import calc_key, check_and_store

from .webhooks import _process_incoming

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/avito")
async def webhook_avito(
    request: Request, http_client: httpx.AsyncClient = Depends(get_http_client)
):
    raw = await request.body()
    try:
        data = await request.json()
    except Exception:
        data = {}

    key = calc_key("avito", raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}

    payload_root = data.get("payload") or {}
    val = payload_root.get("value") or {}

    chat_id = str(val.get("chat_id") or "")
    text = (val.get("content") or {}).get("text") or ""

    item = val.get("item") or {}
    ctx = val.get("context") or {}
    item_id = str(item.get("id") or ctx.get("item_id") or "")
    vacancy_title = item.get("title") or val.get("title") or "Отклик Avito"
    vacancy_desc = item.get("description") or ctx.get("description") or ""

    applicant_id = str(val.get("user_id") or val.get("author_id") or "")

    owner_id = str(
        data.get("account_id")
        or payload_root.get("account_id")
        or val.get("account_id")
        or ""
    ) or None

    if not chat_id:
        logger.warning("Avito webhook: no chat_id, payload=%s", data)
        return {"ok": True, "skipped": True}

    internal = {
        "platform": "avito",
        "owner_id": owner_id,
        "vacancy_id": item_id,
        "vacancy_title": vacancy_title,
        "vacancy_desc": vacancy_desc,
        "applicant": {"id": chat_id, "name": f'user:{applicant_id or "unknown"}'},
        "raw_text": text,
    }
    return await _process_incoming(internal, http_client)


__all__ = ["router"]
