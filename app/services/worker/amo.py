"""Помощники для обработки задач, связанных с amoCRM.

Ниже определены небольшие асинхронные обработчики, используемые сервисом‑воркером.
Каждый обработчик делегирует вызов в :class:`app.adapters.amo_client.AmoClient`.
"""

import logging

from httpx import HTTPStatusError

from app.adapters.amo_client import AmoClient
from app.http_client import get_http_client

logger = logging.getLogger(__name__)


async def handle_amo_create_lead(payload: dict) -> None:
    """Создать сделку в amoCRM.

    Аргументы:
        payload: Содержит ключ ``lead_body`` с описанием создаваемой сделки.
    """

    logger.info("amo.create_lead")
    amo = await AmoClient.create(get_http_client())
    await amo.create_leads(payload["lead_body"])


async def handle_amo_add_note(payload: dict) -> None:
    """Добавить заметку к сделке в amoCRM.

    Аргументы:
        payload: Должен содержать ``lead_id`` и ``text`` для содержимого заметки.
    """

    logger.info("amo.add_note: %s", payload.get("lead_id"))
    amo = await AmoClient.create(get_http_client())
    try:
        await amo.add_note(int(payload["lead_id"]), payload["text"])
    except HTTPStatusError as err:  # pylint: disable=broad-except
        if err.response is not None and err.response.status_code < 500:
            logger.warning("amo.add_note: ошибка: %s", err)
        else:
            raise


async def handle_amo_add_tags(payload: dict) -> None:
    """Добавить теги к сделке в amoCRM.

    Аргументы:
        payload: Должен содержать ``lead_id`` и, при наличии, список ``tags``.
    """

    logger.info("amo.add_tags: %s", payload.get("lead_id"))
    amo = await AmoClient.create(get_http_client())
    try:
        await amo.add_tags(int(payload["lead_id"]), list(payload.get("tags") or []))
    except HTTPStatusError as err:  # pylint: disable=broad-except
        if err.response is not None and err.response.status_code < 500:
            logger.warning("amo.add_tags: ошибка: %s", err)
        else:
            raise


async def handle_amo_update_status(payload: dict) -> None:
    """Обновить этап сделки в amoCRM.

    Аргументы:
        payload: Должен содержать ``lead_id`` и ``status_id`` — новый этап сделки.
    """

    logger.info("amo.update_status: %s", payload.get("lead_id"))
    amo = await AmoClient.create(get_http_client())
    try:
        await amo.update_status(int(payload["lead_id"]), int(payload["status_id"]))
    except HTTPStatusError as err:  # pylint: disable=broad-except
        if err.response is not None and err.response.status_code < 500:
            logger.warning("amo.update_status: ошибка: %s", err)
        else:
            raise
