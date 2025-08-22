from __future__ import annotations
import asyncio, os, logging
from httpx import HTTPStatusError, TimeoutException, ConnectError

from app.services.queue import consume, publish_retry, publish_dlq
from app.adapters.amo_client import ReauthRequired
from app.core.logging_setup import setup_logging

from app.services.worker.hh import handle_hh_send_message, handle_hh_set_state
from app.services.worker.avito import handle_avito_send_message, handle_avito_mark_read
from app.services.worker.amo import (
    handle_amo_create_lead,
    handle_amo_add_note,
    handle_amo_add_tags,
)
from app.services.worker.mirror import (
    handle_mirror_amo_to_tg,
    handle_mirror_tg_to_amo,
    handle_mirror_bot_to_amo,
)

setup_logging("INFO")
logger = logging.getLogger(__name__)

WORKER_MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "6"))


def _is_transient(e: Exception) -> bool:
    if isinstance(e, (TimeoutException, ConnectError)):
        return True
    if isinstance(e, HTTPStatusError):
        return e.response.status_code == 429 or 500 <= e.response.status_code < 600
    return False


async def handle_debug_echo(payload: dict):
    logger.info("RMQ ECHO: %s", payload.get("msg"))


HANDLERS = {
    ("hh", "send_message"): handle_hh_send_message,
    ("hh", "set_state"): handle_hh_set_state,
    ("debug", "echo"): handle_debug_echo,
    ("avito", "send_message"): handle_avito_send_message,
    ("avito", "mark_read"): handle_avito_mark_read,
    ("amo", "amo_create_lead"): handle_amo_create_lead,
    ("amo", "amo_add_note"): handle_amo_add_note,
    ("amo", "amo_add_tags"): handle_amo_add_tags,
    ("mirror", "amo_to_tg"): handle_mirror_amo_to_tg,
    ("mirror", "tg_to_amo"): handle_mirror_tg_to_amo,
    ("mirror", "bot_to_amo"): handle_mirror_bot_to_amo,
}


async def handle(payload: dict, attempts: int):
    try:
        plat = payload.get("platform")
        act = payload.get("action")
        handler = HANDLERS.get((plat, act))
        if not handler:
            raise RuntimeError(f"unknown task: {payload}")
        await handler(payload)

    except ReauthRequired as e:
        logger.warning("ReauthRequired: %s", e)
        await publish_dlq(payload, attempts + 1, f"ReauthRequired: {e}")

    except Exception as e:
        if _is_transient(e) and attempts + 1 < WORKER_MAX_ATTEMPTS:
            await publish_retry(payload, attempts + 1)
        else:
            logger.exception("Task failed terminally")
            await publish_dlq(payload, attempts + 1, str(e))


async def run_forever():
    await consume(handle)


if __name__ == "__main__":
    asyncio.run(run_forever())

