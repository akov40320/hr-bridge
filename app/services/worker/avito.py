"""Обработчики, выполняющие задачи, связанные с Avito.

Модуль содержит асинхронные функции, которые рабочий процессор использует для
взаимодействия с API Avito. Эти функции являются небольшими обёртками над
соответствующими вызовами адаптера и намеренно похожи на обработчики для HH,
чтобы поведение было единообразным между площадками.
"""

# pylint: disable=duplicate-code

import logging

from app.adapters import avito as avito_adapt
from app.services.common_request import perform_request
from app.services.dedup import calc_key, once

logger = logging.getLogger(__name__)


async def handle_avito_send_message(payload: dict) -> None:
    """Отправить сообщение кандидату через Avito.

    Args:
        payload: словарь, который должен содержать внешний идентификатор
            сообщения и текст. Дополнительно может быть указан ``owner_id`` —
            идентификатор аккаунта.
    """

    msg_key = payload.get("msg_key")

    async def _op():
        logger.info("avito.send_message: %s", payload.get("external_id"))
        await perform_request(
            avito_adapt.send_message,
            payload["external_id"],
            payload["text"],
            owner_id=payload.get("owner_id"),
        )

    if msg_key:
        dedup = calc_key("avito_send_message", msg_key)
        if not await once(dedup, 72 * 3600, _op):
            return
    else:
        await _op()


async def handle_avito_mark_read(payload: dict) -> None:
    """Отметить диалог как прочитанный на Avito.

    Args:
        payload: словарь, который должен содержать внешний идентификатор
            сообщения и может включать ``owner_id`` с идентификатором аккаунта.
    """

    logger.info("avito.mark_read: %s", payload.get("external_id"))
    await perform_request(
        avito_adapt.mark_read,
        payload["external_id"],
        owner_id=payload.get("owner_id"),
    )
