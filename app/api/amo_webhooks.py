"""Endpoints handling incoming AmoCRM webhooks."""

from typing import Any, Mapping, cast
import json
import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.http_client import get_http_client
from app.services.dedup import calc_key, check_and_store
from app.services.hh_mapping import load as hh_map_load
from app.services.queue import RabbitMQClient, rabbitmq
from app.services.hh_status_sync import sync_hh_status
from app.store import find_link
from app.store_status import set_last_transition
from .utils import events_from_form

logger = logging.getLogger(__name__)
router = APIRouter()


async def parse_status_events(request: Request) -> list[tuple[int, int]]:
    """Вернуть список пар (lead_id, status_id) из полезной нагрузки вебхука Amo."""
    events: list[tuple[int, int]] = []
    try:
        data = await request.json()
        if isinstance(data, dict) and data.get("leads", {}).get("status"):
            for it in data["leads"]["status"]:
                lead_id = int(it["id"])
                status_id = int(it.get("new_status_id") or it.get("status_id"))
                events.append((lead_id, status_id))
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        body = (await request.body()).decode("utf-8", errors="replace")
        logger.warning(
            "Не удалось распарсить вебхук статуса AmoCRM: %s; body=%s", exc, body[:200]
        )
        raise HTTPException(status_code=400, detail=f"Invalid payload: {exc}") from exc

    if not events:
        form = await request.form()
        # Превращаем FormData в обычный dict[str, str]
        data_map: Mapping[str, str] = {
            k: (v if isinstance(v, str) else getattr(v, "filename", str(v)))
            for k, v in form.multi_items()
        }
        events = events_from_form(cast(Mapping[str, str], data_map))
    return events


async def handle_avito_event(
    _lead_id: int,
    _status_id: int,
    link: dict[str, Any],
    queue_client: RabbitMQClient = rabbitmq,
) -> None:
    """Отметить переписку Avito как прочитанную для указанного лида."""
    ext_id = link.get("external_id")
    owner_id = link.get("owner_id")
    await queue_client.publish_task(
        {
            "platform": "avito",
            "action": "mark_read",
            "payload": {
                "external_id": ext_id,
                "owner_id": owner_id,
            },
        }
    )


@router.post("/webhooks/amo")
async def amo_webhook(
    request: Request,
    http_client: httpx.AsyncClient = Depends(get_http_client),
    queue_client: RabbitMQClient = Depends(lambda: rabbitmq),
):
    """Обработать вебхук AmoCRM и синхронизировать статусы лидов с внешними площадками."""
    raw = await request.body()
    key = calc_key("amo", raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}

    hh_map_load()
    events = await parse_status_events(request)

    for lead_id, status_id in events:
        await set_last_transition(lead_id, status_id, int(time.time()))
        link = await find_link(lead_id)
        if not link:
            logger.warning("НЕТ СВЯЗИ ДЛЯ ЛИДА %s", lead_id)
            continue

        platform = link.get("platform")
        if platform == "hh":
            await sync_hh_status(lead_id, status_id, link, http_client, queue_client)
        elif platform == "avito":
            await handle_avito_event(lead_id, status_id, link, queue_client)

    return {"ok": True, "events": len(events)}


__all__ = ["router", "parse_status_events"]
