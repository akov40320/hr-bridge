"""Обработчики для задач, специфичных для Avito.

Модуль содержит асинхронные обработчики, используемые воркером для работы с
Avito API. Функции представляют собой небольшие обёртки над вызовами адаптера
и намеренно похожи на обработчики для HH для единообразия поведения.
"""

# pylint: disable=duplicate-code

import logging

from app.adapters import avito as avito_adapt
from app.services.common_request import perform_request

logger = logging.getLogger(__name__)


async def handle_avito_send_message(payload: dict) -> None:
    """Отправить сообщение кандидату через Avito.

    Аргументы:
        payload: Должен содержать внешний ID переписки и текст сообщения;
            опционально может содержать ``owner_id`` (ID аккаунта).
    """

    logger.info("avito.send_message: %s", payload.get("external_id"))
    await perform_request(
        avito_adapt.send_message,
        payload["external_id"],
        payload["text"],
        owner_id=payload.get("owner_id"),
    )


async def handle_avito_mark_read(payload: dict) -> None:
    """Пометить переписку как прочитанную в Avito.

    Аргументы:
        payload: Должен содержать внешний ID переписки и, при необходимости,
            ``owner_id`` (ID аккаунта).
    """

    logger.info("avito.mark_read: %s", payload.get("external_id"))
    await perform_request(
        avito_adapt.mark_read,
        payload["external_id"],
        owner_id=payload.get("owner_id"),
    )
