"""Helpers for processing tasks related to amoCRM.

The functions defined here are small asynchronous handlers that are used by the
worker service.  Each handler delegates to :class:`app.adapters.amo_client.AmoClient`
to perform the actual API call.
"""

import logging
import time

from httpx import HTTPStatusError

from app.adapters.amo_client import AmoClient
from app.http_client import get_http_client
from app.services.dedup import calc_key, once
from app.store_status import get_last_transition, set_last_transition

logger = logging.getLogger(__name__)


async def handle_amo_create_lead(payload: dict) -> None:
    """Создать лид в amoCRM.

    Args:
        payload: словарь с ключом ``lead_body``, описывающим создаваемый лид.
    """

    msg_key = payload.get("msg_key")

    async def _op():
        logger.info("amo.create_lead")
        amo = await AmoClient.create(get_http_client())
        await amo.create_leads(payload["lead_body"])

    if msg_key:
        dedup = calc_key("amo_create_lead", msg_key)
        if not await once(dedup, 72 * 3600, _op):
            return
    else:
        await _op()


async def handle_amo_add_note(payload: dict) -> None:
    """Добавить примечание к лиду в amoCRM.

    Args:
        payload: должен содержать ``lead_id`` и ``text`` с содержимым примечания.
    """

    logger.info("amo.add_note: %s", payload.get("lead_id"))
    amo = await AmoClient.create(get_http_client())
    try:
        await amo.add_note(int(payload["lead_id"]), payload["text"])
    except HTTPStatusError as err:  # pylint: disable=broad-except
        if err.response is not None and err.response.status_code < 500:
            logger.warning("amo.add_note не удалось: %s", err)
        else:
            raise


async def handle_amo_add_tags(payload: dict) -> None:
    """Добавить теги к лиду в amoCRM.

    Args:
        payload: должен содержать ``lead_id`` и может включать список ``tags``.
    """

    logger.info("amo.add_tags: %s", payload.get("lead_id"))
    amo = await AmoClient.create(get_http_client())
    try:
        await amo.add_tags(int(payload["lead_id"]), list(payload.get("tags") or []))
    except HTTPStatusError as err:  # pylint: disable=broad-except
        if err.response is not None and err.response.status_code < 500:
            logger.warning("amo.add_tags не удалось: %s", err)
        else:
            raise


async def handle_amo_update_status(payload: dict) -> None:
    """Обновить статус лида в amoCRM.

    Args:
        payload: должен содержать ``lead_id`` и ``status_id`` с новым статусом.
            Необязательный ``ts`` указывает время запроса, чтобы избежать
            применения устаревших обновлений.
    """

    lead_id = int(payload["lead_id"])
    status_id = int(payload["status_id"])
    ts = int(payload.get("ts") or time.time())

    last = await get_last_transition(lead_id)
    if last and last.ts >= ts:
        logger.info("amo.update_status: устаревший переход для лида %s", lead_id)
        return

    logger.info("amo.update_status: %s", lead_id)
    amo = await AmoClient.create(get_http_client())
    try:
        await amo.update_status(lead_id, status_id)
    except HTTPStatusError as err:  # pylint: disable=broad-except
        if err.response is not None and err.response.status_code < 500:
            logger.warning("amo.update_status не удалось: %s", err)
        else:
            raise
    else:
        await set_last_transition(lead_id, status_id, ts)
