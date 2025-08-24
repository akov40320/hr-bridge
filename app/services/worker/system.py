"""Handlers for internal system tasks."""

import logging
import time

from app.db.token_store import DbTokenStore
from app.http_client import get_http_client
from app.services.hh_autofill import autofill_hh_mapping

logger = logging.getLogger(__name__)


async def handle_system_hh_autofill(payload: dict) -> None:
    """Build HH status mapping based on AmoCRM pipelines."""
    logger.info("system.hh_autofill")
    tok = await DbTokenStore("amo").load()
    if (
        not tok
        or not tok.get("access_token")
        or int(tok.get("expires_at", 0)) <= int(time.time()) + 30
    ):
        raise RuntimeError("amo token missing/expired")
    await autofill_hh_mapping(get_http_client())
