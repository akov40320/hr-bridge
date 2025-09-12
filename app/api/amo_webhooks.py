"""Эндпоинты для обработки входящих вебхуков AmoCRM."""

from typing import Any, Mapping, cast
# pylint: disable=line-too-long
import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.adapters.amo_client import AmoClient
from app.core.config import get_settings
from app.http_client import get_http_client
from app.services.dedup import calc_key, check_and_store
from app.services.hh_mapping import get as hh_map_get, load as hh_map_load
from app.services.queue import RabbitMQClient, rabbitmq
from app.store import find_link
from .utils import (
    REFUSAL_TEXT_TO_HH,
    events_from_form,
    is_refusal_code,
    norm_reason,
    refusal_text,
)

logger = logging.getLogger(__name__)
router = APIRouter()


async def parse_status_events(request: Request) -> list[tuple[int, int]]:
    """Возвращает список пар (lead_id, status_id) из полезной нагрузки вебхука Amo."""
    events: list[tuple[int, int]] = []
    data: Any | None = None
    ctype = request.headers.get("content-type", "")
    if "json" in ctype:
        try:
            data = await request.json()
        except json.JSONDecodeError as exc:
            body = (await request.body()).decode("utf-8", errors="replace")
            logger.warning(
                "Не удалось разобрать вебхук статуса AmoCRM: %s; body=%s", exc, body[:200]
            )
    if data is not None:
        try:
            if isinstance(data, dict) and data.get("leads", {}).get("status"):
                for it in data["leads"]["status"]:
                    lead_id = int(it["id"])
                    status_id = int(it.get("new_status_id") or it.get("status_id"))
                    events.append((lead_id, status_id))
        except (KeyError, ValueError) as exc:
            body = (await request.body()).decode("utf-8", errors="replace")
            logger.warning(
                "Не удалось разобрать вебхук статуса AmoCRM: %s; body=%s", exc, body[:200]
            )
            raise HTTPException(status_code=400, detail=f"Invalid payload: {exc}") from exc

    if not events:
        form = await request.form()
        # Преобразуем FormData к словарю вида dict[str, str]
        data_map: Mapping[str, str] = {
            k: (v if isinstance(v, str) else getattr(v, "filename", str(v)))
            for k, v in form.multi_items()
        }
        events = events_from_form(cast(Mapping[str, str], data_map))
    return events


async def _fetch_refusal_reason(
    lead_id: int, client: httpx.AsyncClient, field_id: int
) -> str | None:
    """Получает текст причины отказа для указанного лида."""
    try:
        amo = await AmoClient.create(client)
        lead = await amo.get_lead(lead_id)
    except httpx.HTTPError as exc:  # pragma: no cover - network failure
        logger.exception("Не удалось получить лид %s: %s", lead_id, exc)
        return None

    cfv = lead.get("custom_fields_values") or []
    field = next(
        (f for f in cfv if int(f.get("field_id") or 0) == int(field_id)),
        None,
    )
    if not field:
        return ""
    values = field.get("values") or []
    if not values:
        return ""
    value = values[0].get("value")
    if isinstance(value, dict):
        return value.get("value") or value.get("text") or ""
    return value or ""


async def handle_hh_event(
    lead_id: int,
    status_id: int,
    link: dict[str, Any],
    http_client: httpx.AsyncClient,
    queue_client: RabbitMQClient = rabbitmq,
) -> None:
    """Обновляет состояние в HH на основе изменения статуса в AmoCRM."""
    s = get_settings()
    ext_id = link.get("external_id")
    owner_id = link.get("owner_id")
    state = await hh_map_get(status_id)
    if state is None:
        await queue_client.publish_task({"platform": "system", "action": "hh_autofill"})
        logger.info("Неизвестный статус Amo %s — поставлена задача hh_autofill", status_id)
        return
    if not ext_id:
        return

    final_state = state
    if is_refusal_code(state) and s.AMO_CF_REFUSAL_REASON_ID:
        reason_text = await _fetch_refusal_reason(
            lead_id, http_client, s.AMO_CF_REFUSAL_REASON_ID
        )
        if reason_text is not None:
            mapped = REFUSAL_TEXT_TO_HH.get(norm_reason(reason_text))
            if mapped:
                final_state = mapped
            elif not reason_text.strip():
                try:
                    pretty = refusal_text(state) or state
                    amo = await AmoClient.create(http_client)
                    await amo.update_lead_custom_fields(
                        lead_id, {s.AMO_CF_REFUSAL_REASON_ID: pretty}
                    )
                except httpx.HTTPError:
                    logger.warning("Не удалось скопировать текст причины отказа")

    await queue_client.publish_task(
        {
            "platform": "hh",
            "action": "set_state",
            "external_id": ext_id,
            "target_state": final_state,
            "owner_id": owner_id,
        }
    )


async def handle_avito_event(
    _lead_id: int,
    _status_id: int,
    link: dict[str, Any],
    queue_client: RabbitMQClient = rabbitmq,
) -> None:
    """Помечает переписку Avito как прочитанную для данного лида."""
    ext_id = link.get("external_id")
    owner_id = link.get("owner_id")
    await queue_client.publish_task(
        {
            "platform": "avito",
            "action": "mark_read",
            "external_id": ext_id,
            "owner_id": owner_id,
        }
    )


@router.post("/webhooks/amo")
async def amo_webhook(
    request: Request,
    http_client: httpx.AsyncClient = Depends(get_http_client),
    queue_client: RabbitMQClient = Depends(lambda: rabbitmq),
):
    """Обрабатывает вебхук AmoCRM и синхронизирует статусы лида во внешние
    платформы."""
    raw = await request.body()
    key = calc_key("amo", raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}

    await hh_map_load()
    events = await parse_status_events(request)

    for lead_id, status_id in events:
        link = await find_link(lead_id)
        if not link:
            logger.warning("НЕТ СВЯЗИ ДЛЯ ЛИДА %s", lead_id)
            continue

        platform = link.get("platform")
        if platform == "hh":
            await handle_hh_event(lead_id, status_id, link, http_client, queue_client)
        elif platform == "avito":
            await handle_avito_event(lead_id, status_id, link, queue_client)

    return {"ok": True, "events": len(events)}


__all__ = ["router", "parse_status_events"]
