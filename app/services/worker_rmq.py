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
    handle_amo_update_status,
)
from app.services.worker.avito import handle_avito_mark_read, handle_avito_send_message
from app.services.worker.hh import handle_hh_send_message, handle_hh_set_state
from app.services.worker.system import handle_system_hh_autofill
from app.services.worker.mirror import (
    handle_mirror_amo_to_tg,
    handle_mirror_bot_to_amo,
    handle_mirror_tg_to_amo,
)


setup_logging("INFO")
logger = logging.getLogger(__name__)

WORKER_MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "6"))


def _is_transient(exc: Exception) -> bool:
    """Вернуть True, если исключение временное и операцию можно повторить."""

    if isinstance(exc, (TimeoutException, ConnectError)):
        return True
    if isinstance(exc, HTTPStatusError):
        return exc.response.status_code == 429 or 500 <= exc.response.status_code < 600
    return False


async def handle_debug_echo(payload: dict) -> None:
    """Записать отладочное сообщение, пришедшее из очереди."""

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
    ("amo", "amo_update_status"): handle_amo_update_status,
    ("system", "hh_autofill"): handle_system_hh_autofill,
    ("mirror", "amo_to_tg"): handle_mirror_amo_to_tg,
    ("mirror", "tg_to_amo"): handle_mirror_tg_to_amo,
    ("mirror", "bot_to_amo"): handle_mirror_bot_to_amo,
}


async def handle(
    payload: dict, attempts: int, queue_client: RabbitMQClient = rabbitmq
) -> None:
    """Направить загрузку в соответствующий обработчик с логикой повторов."""

    try:
        plat = payload.get("platform")
        act = payload.get("action")
        logger.info(
            "worker: handle platform=%s action=%s attempts=%s",
            plat,
            act,
            attempts,
        )
        if not isinstance(plat, str) or not isinstance(act, str):
            raise RuntimeError(f"unknown task: {payload}")
        handler = HANDLERS.get((plat, act))
        if not handler:
            raise RuntimeError(f"unknown task: {payload}")
        data = payload.get("payload") or {}
        if payload.get("msg_key") is not None:
            data.setdefault("msg_key", payload["msg_key"])
        await handler(data)
        logger.info(
            "worker: done platform=%s action=%s attempts=%s",
            plat,
            act,
            attempts,
        )

    except ReauthRequired as err:
        logger.warning("ReauthRequired: %s", err)
        await queue_client.publish_dlq(payload, attempts + 1, f"ReauthRequired: {err}")

    except Exception as err:  # pylint: disable=broad-exception-caught
        if _is_transient(err) and attempts + 1 < WORKER_MAX_ATTEMPTS:
            await queue_client.publish_retry(payload, attempts + 1)
        else:
            logger.exception("Задача окончательно провалилась")
            await queue_client.publish_dlq(payload, attempts + 1, str(err))


async def run_forever(queue_client: RabbitMQClient = rabbitmq) -> None:
    """Непрерывно потреблять задачи из очереди."""
    logger.info(
        "worker:start RABBITMQ_URL=%s EX=%s Q=%s RETRY_Q=%s DLQ=%s",
        os.getenv("RABBITMQ_URL"),
        os.getenv("RMQ_EXCHANGE"),
        os.getenv("RMQ_TASK_QUEUE"),
        os.getenv("RMQ_RETRY_QUEUE"),
        os.getenv("RMQ_DLQ_QUEUE"),
    )
    logger.info("worker:начинаю обработку ...")
    await queue_client.consume(
        lambda payload, attempts: handle(payload, attempts, queue_client)
    )


if __name__ == "__main__":
    asyncio.run(run_forever())
