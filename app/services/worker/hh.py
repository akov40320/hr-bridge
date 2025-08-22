import logging

from app.adapters import hh as hh_adapt
from app.http_client import get_http_client

logger = logging.getLogger(__name__)


async def handle_hh_send_message(payload: dict):
    logger.info("hh.send_message: %s", payload.get("external_id"))
    client = get_http_client()
    await hh_adapt.send_message(
        payload["external_id"],
        payload["text"],
        employer_id=payload.get("owner_id"),
        client=client,
    )


async def handle_hh_set_state(payload: dict):
    logger.info(
        "hh.set_state: %s -> %s",
        payload.get("external_id"),
        payload.get("target_state"),
    )
    client = get_http_client()
    await hh_adapt.set_employer_state(
        payload["external_id"],
        payload["target_state"],
        employer_id=payload.get("owner_id"),
        client=client,
    )
