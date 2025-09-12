"""Обработчики воркера для сервиса HeadHunter (hh.ru).

Функции-обработчики воркера проксируют задачи в адаптер HH.
"""

import logging

from app.adapters import hh as hh_adapt
from app.http_client import get_http_client

logger = logging.getLogger(__name__)


async def handle_hh_send_message(payload: dict):
    """Отправить сообщение кандидату.

    payload:
        negotiation_id (str) — ID отклика/приглашения (nid)
        external_id (str) — альтернативный ID отклика/приглашения
        text (str) — текст сообщения
        owner_id (str|None) — работодатель/менеджер
    """
    nid = payload.get("negotiation_id") or payload.get("external_id")
    if not nid:
        raise ValueError("negotiation_id or external_id is required")
    text = payload["text"]
    owner_id = payload.get("owner_id")

    logger.info("hh: отправка сообщения: %s текст=%r", nid, text[:40])
    client = get_http_client()
    await hh_adapt.send_message(
        response_id=nid,
        text=text,
        employer_id=owner_id,
        client=client,
    )



async def handle_hh_set_state(payload: dict):
    """Перевести отклик на следующий этап.

    payload:
        negotiation_id (str) — ID отклика/приглашения (nid)
        external_id (str) — альтернативный ID отклика/приглашения
        action_id (str) или target_state (str) — действие, например 'phone_interview', 'interview'
        owner_id (str|None) — работодатель/менеджер
    """
    nid = payload.get("negotiation_id") or payload.get("external_id")
    if not nid:
        raise ValueError("negotiation_id or external_id is required")
    target_state = payload.get("action_id") or payload.get("target_state")
    if not target_state:
        raise ValueError("action_id or target_state is required")
    owner_id = payload.get("owner_id")

    logger.info("hh: изменение состояния: %s -> %s", nid, target_state)
    client = get_http_client()
    await hh_adapt.set_employer_state(
        response_id=nid,
        target_state=target_state,
        employer_id=owner_id,
        client=client,
    )
