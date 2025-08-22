import logging

from app.adapters.amo_client import AmoClient
from app.http_client import get_http_client

logger = logging.getLogger(__name__)


async def handle_amo_create_lead(payload: dict):
    logger.info("amo.create_lead")
    amo = await AmoClient.create(get_http_client())
    await amo.create_leads(payload["lead_body"])


async def handle_amo_add_note(payload: dict):
    logger.info("amo.add_note: %s", payload.get("lead_id"))
    amo = await AmoClient.create(get_http_client())
    await amo.add_note(int(payload["lead_id"]), payload["text"])


async def handle_amo_add_tags(payload: dict):
    logger.info("amo.add_tags: %s", payload.get("lead_id"))
    amo = await AmoClient.create(get_http_client())
    await amo.add_tags(int(payload["lead_id"]), list(payload.get("tags") or []))
