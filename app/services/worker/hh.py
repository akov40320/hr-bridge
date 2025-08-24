"""Worker handlers for the HeadHunter (hh.ru) service.

Функции-обработчики воркера. Проксируют задачи в адаптер HH.
"""

import logging

from app.adapters import hh as hh_adapt
from app.http_client import get_http_client

logger = logging.getLogger(__name__)


async def handle_hh_send_message(payload: dict):
    """Отправить сообщение кандидату.

    payload:
        negotiation_id (str) — ID отклика/приглашения (nid)
        text (str) — текст сообщения
        owner_id (str|None) — работодатель/менеджер
    """
    nid = payload["negotiation_id"]
    text = payload["text"]
    owner_id = payload.get("owner_id")

    logger.info("hh.send_message: %s text=%r", nid, text[:40])
    client = get_http_client()
    await hh_adapt.send_message(
        negotiation_id=nid,
        text=text,
        employer_id=owner_id,
        client=client,
    )


async def handle_hh_set_state(payload: dict):
    """Перевести отклик на следующий этап.

    payload:
        negotiation_id (str) — ID отклика/приглашения (nid)
        action_id (str) — действие, например 'phone_interview', 'interview'
        owner_id (str|None) — работодатель/менеджер
    """
    nid = payload["negotiation_id"]
    action_id = payload["action_id"]
    owner_id = payload.get("owner_id")

    logger.info("hh.set_state: %s -> %s", nid, action_id)
    client = get_http_client()
    await hh_adapt.set_state_action(
        negotiation_id=nid,
        action_id=action_id,
        employer_id=owner_id,
        client=client,
    )
