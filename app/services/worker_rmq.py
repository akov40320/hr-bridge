"""RabbitMQ worker entry point."""

from __future__ import annotations

import asyncio
import logging
import os

from httpx import ConnectError, HTTPStatusError, TimeoutException

from app.adapters.amo_client import ReauthRequired
from app.core.logging_setup import setup_logging
from app.services.queue import RabbitMQClient, rabbitmq
from app.services.worker.amo import (
    handle_amo_add_note,
    handle_amo_add_tags,
    handle_amo_create_lead,
)
from app.services.worker.avito import handle_avito_mark_read, handle_avito_send_message
from app.services.worker.hh import handle_hh_send_message, handle_hh_set_state
from app.services.worker.mirror import (
    handle_mirror_amo_to_tg,
    handle_mirror_bot_to_amo,
    handle_mirror_tg_to_amo,
)


setup_logging("INFO")
logger = logging.getLogger(__name__)

WORKER_MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "6"))


def _is_transient(exc: Exception) -> bool:
    """Return True if the exception is temporary and can be retried."""

    if isinstance(exc, (TimeoutException, ConnectError)):
        return True
    if isinstance(exc, HTTPStatusError):
        return exc.response.status_code == 429 or 500 <= exc.response.status_code < 600
    return False


async def handle_debug_echo(payload: dict) -> None:
    """Log a debug message coming from the queue."""

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


async def handle(
    payload: dict, attempts: int, queue_client: RabbitMQClient = rabbitmq
) -> None:
    """Dispatch the payload to the appropriate handler with retry logic."""

    try:
        plat = payload.get("platform")
        act = payload.get("action")
        handler = HANDLERS.get((plat, act))
        if not handler:
            raise RuntimeError(f"unknown task: {payload}")
        await handler(payload)

    except ReauthRequired as err:
        logger.warning("ReauthRequired: %s", err)
        await queue_client.publish_dlq(payload, attempts + 1, f"ReauthRequired: {err}")

    except Exception as err:  # pylint: disable=broad-exception-caught
        if _is_transient(err) and attempts + 1 < WORKER_MAX_ATTEMPTS:
            await queue_client.publish_retry(payload, attempts + 1)
        else:
            logger.exception("Task failed terminally")
            await queue_client.publish_dlq(payload, attempts + 1, str(err))


async def run_forever(queue_client: RabbitMQClient = rabbitmq) -> None:
    """Continuously consume tasks from the queue."""

    await queue_client.consume(
        lambda payload, attempts: handle(payload, attempts, queue_client)
    )


if __name__ == "__main__":
    asyncio.run(run_forever())
