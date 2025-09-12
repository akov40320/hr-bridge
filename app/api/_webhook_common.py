"""Общая логика обработки вебхуков с сайтов вакансий."""

import logging
from typing import Callable

import httpx

from app.adapters.amo_client import AmoClient
from app.services.dedup import calc_key, check_and_store
from app.services.lead_processor import (
    enrich_applicant,
    create_lead,
    send_invite,
    tag_lead,
)
from app.models import IncomingPayload

logger = logging.getLogger(__name__)


async def process_job_board_webhook(
    platform: str,
    raw: bytes,
    http_client: httpx.AsyncClient,
    parse_payload: Callable[[bytes], IncomingPayload],
) -> dict:
    """Обработать входящий вебхук job board.

    Выполняет дедупликацию, парсинг payload и обработку лида.
    """
    key = calc_key(platform, raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}

    try:
        payload = parse_payload(raw)
    except ValueError as exc:
        logger.warning("вебхук %s: %s; payload=%s", platform, exc, raw)
        return {"ok": True, "skipped": True}

    try:
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
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("вебхук %s: внутренняя ошибка", platform)
        return {"ok": False, "error": "internal_error"}


__all__ = ["process_job_board_webhook"]
