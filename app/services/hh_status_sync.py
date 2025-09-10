"""Helpers for synchronizing AmoCRM lead statuses with HeadHunter.

This module exposes :func:`sync_hh_status` which takes a lead/status pair
and publishes a task to update the corresponding negotiation state on HH.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.adapters.amo_client import AmoClient
from app.core.config import get_settings
from app.services.hh_mapping import get as hh_map_get
from app.services.queue import RabbitMQClient, rabbitmq
from app.events import UpdateStatus, UpdateStatusPayload
from app.api.utils import (
    REFUSAL_TEXT_TO_HH,
    is_refusal_code,
    norm_reason,
    refusal_text,
)

logger = logging.getLogger(__name__)


async def _fetch_refusal_reason(
    lead_id: int, client: httpx.AsyncClient, field_id: int
) -> str | None:
    """Retrieve refusal reason text for the given lead."""
    try:
        amo = await AmoClient.create(client)
        lead = await amo.get_lead(lead_id)
    except httpx.HTTPError as exc:  # pragma: no cover - network failure
        logger.exception("Failed to fetch lead %s: %s", lead_id, exc)
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


async def sync_hh_status(
    lead_id: int,
    status_id: int,
    link: dict[str, Any],
    http_client: httpx.AsyncClient,
    queue_client: RabbitMQClient = rabbitmq,
) -> None:
    """Update state in HH based on AmoCRM status change."""
    s = get_settings()
    ext_id = link.get("external_id")
    owner_id = link.get("owner_id")
    state = hh_map_get(status_id)
    if not (state and ext_id):
        return

    final_state = state
    if is_refusal_code(state) and getattr(s, "AMO_CF_REFUSAL_REASON_ID", None):
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
                    logger.warning("Failed to copy refusal text")

    event = UpdateStatus(
        platform="hh",
        action="set_state",
        payload=UpdateStatusPayload(
            external_id=ext_id,
            target_state=final_state,
            owner_id=owner_id,
        ),
    )
    await queue_client.publish_task(event.model_dump(exclude_none=True))


__all__ = ["sync_hh_status"]
