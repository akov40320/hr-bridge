"""Обработчики фоновых задач, используемых потребителем RMQ."""

import logging

from app.adapters import avito as avito_adapt, hh as hh_adapt
from app.adapters.amo_client import AmoClient
from app.http_client import get_http_client
from app.services.worker.amo import (
    handle_amo_add_note,
    handle_amo_add_tags,
    handle_amo_update_status,
)
from app.services.worker.mirror import (
    handle_mirror_amo_to_tg,
    handle_mirror_bot_to_amo,
    handle_mirror_tg_to_amo,
)
from app.services.worker.system import handle_system_hh_autofill

# Логгер для отслеживания выполнения задач
logger = logging.getLogger(__name__)


async def handle_task(p: dict, _attempts: int = 0):
    """Обработать фоновую задачу в зависимости от платформы и действия."""

    # Отключаем предупреждения Pylint по количеству веток и возвратов
    # pylint: disable=too-many-return-statements,too-many-branches

    logger.info("Получена задача: %s", p)

    if p.get("platform") == "system" and p.get("action") == "hh_autofill":
        await handle_system_hh_autofill(p)
        return

    if p.get("platform") == "hh" and p.get("action") == "set_state":
        nid = p.get("negotiation_id") or p.get("external_id")
        action_id = p.get("action_id") or p.get("target_state")
        if not nid or not action_id:
            raise RuntimeError(f"hh.set_state: отсутствует nid или action_id в {p}")
        logger.info("hh: изменение состояния отклика %s", nid)
        await hh_adapt.set_employer_state(
            response_id=nid,
            target_state=action_id,
            employer_id=p.get("owner_id"),
            client=get_http_client(),
        )
        return
    if p.get("platform") == "hh" and p.get("action") == "send_message":
        nid = p.get("negotiation_id") or p.get("external_id")
        if not nid:
            raise RuntimeError(f"hh.send_message: отсутствует nid в {p}")
        logger.info("hh: отправка сообщения для отклика %s", nid)
        await hh_adapt.send_message(
            response_id=nid,
            text=p.get("text") or "",
            employer_id=p.get("owner_id"),
            client=get_http_client(),
        )
        return

    if p["platform"] == "avito" and p["action"] == "mark_read":
        logger.info("avito: пометка переписки %s как прочитанной", p["external_id"])
        await avito_adapt.mark_read(
            p["external_id"],
            owner_id=p.get("owner_id"),
            client=get_http_client(),
        )
        return

    if p["platform"] == "avito" and p["action"] == "send_message":
        logger.info("avito: отправка сообщения в переписку %s", p["external_id"])
        await avito_adapt.send_message(
            p["external_id"],
            p.get("text") or "",
            owner_id=p.get("owner_id"),
            client=get_http_client(),
        )
        return

    if p["platform"] == "amo" and p["action"] == "amo_create_lead":
        logger.info("amo: создание лида")
        amo = await AmoClient.create(get_http_client())
        await amo.create_leads(p["lead_body"])
        return

    if p.get("platform") == "amo" and p.get("action") == "amo_add_note":
        logger.info("amo: добавление примечания")
        await handle_amo_add_note(p)
        return

    if p.get("platform") == "amo" and p.get("action") == "amo_add_tags":
        logger.info("amo: добавление тегов")
        await handle_amo_add_tags(p)
        return

    if p.get("platform") == "amo" and p.get("action") == "amo_update_status":
        logger.info("amo: обновление статуса")
        await handle_amo_update_status(p)
        return

    if p.get("platform") == "mirror" and p.get("action") == "amo_to_tg":
        logger.info("mirror: AmoCRM -> Telegram")
        await handle_mirror_amo_to_tg(p)
        return

    if p.get("platform") == "mirror" and p.get("action") == "tg_to_amo":
        logger.info("mirror: Telegram -> AmoCRM")
        await handle_mirror_tg_to_amo(p)
        return

    if p.get("platform") == "mirror" and p.get("action") == "bot_to_amo":
        logger.info("mirror: бот -> AmoCRM")
        await handle_mirror_bot_to_amo(p)
        return
    logger.error("Неизвестная задача: %s", p)
    raise RuntimeError(f"Неизвестная задача: {p}")


__all__ = ["handle_task"]
