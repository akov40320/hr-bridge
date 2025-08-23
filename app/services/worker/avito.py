import logging

from app.adapters import avito as avito_adapt
from app.services.common_request import perform_request

logger = logging.getLogger(__name__)


async def handle_avito_send_message(payload: dict):
    logger.info("avito.send_message: %s", payload.get("external_id"))
    await perform_request(
        avito_adapt.send_message,
        payload["external_id"],
        payload["text"],
        owner_id=payload.get("owner_id"),
    )


async def handle_avito_mark_read(payload: dict):
    logger.info("avito.mark_read: %s", payload.get("external_id"))
    await perform_request(
        avito_adapt.mark_read,
        payload["external_id"],
        owner_id=payload.get("owner_id"),
    )
