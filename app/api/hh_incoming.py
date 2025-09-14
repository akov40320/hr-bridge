"""Обработчик входящих вебхуков от HeadHunter (HH)."""

import logging
import json

import httpx
from fastapi import APIRouter, Depends, Request, Response
from starlette.requests import ClientDisconnect

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
    """Обработать вебхук HH и передать новые отклики дальше.

    Пропускает события смены статуса работодателя (только логирует и возвращает ok).
    """
    if (
        request.method == "HEAD"
        or request.headers.get("content-length") in (None, "0")
    ):
        raw = b""
    else:
        try:
            raw = await request.body()
        except ClientDisconnect:
            return Response(status_code=400)

    # Безопасное логирование тела
    try:
        log.info("HH webhook: получено тело: %s", raw.decode("utf-8"))
    except UnicodeDecodeError:
        log.info("HH webhook: получено (бинарное) тело: %s", raw)

    # Игнорирование событий смены статуса
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
        action_type = str(data.get("action_type") or "").strip().upper()
        if action_type == "NEGOTIATION_EMPLOYER_STATE_CHANGE":
            log.info(
                "HH webhook: смена статуса -> пропуск (owner_id=%s)",
                owner_id,
            )
            return {"ok": True, "ignored": True, "event": action_type}
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        AttributeError,
    ):  # pragma: no cover
        pass

    return await process_job_board_webhook(
        "hh", raw, http_client, lambda raw: parse_hh_payload(raw, owner_id)
    )


__all__ = ["router"]
