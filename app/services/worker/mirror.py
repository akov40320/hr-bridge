"""Модуль содержит асинхронные обработчики, пересылающие сообщения между AMO CRM и Telegram.

Он отправляет сообщения из AMO в Telegram, зеркалирует сообщения из Telegram в AMO
и пересылает в AMO чаты сообщения, созданные ботом. Все обработчики принимают
словарь ``payload`` с деталями, зависящими от направления зеркалирования.
"""

import logging
import time
from aiogram import Bot

from app.adapters.amochats import send_text_from_manager, ensure_chat_created, send_text_from_client
from app.core.config import get_settings
from app.services.dedup import check_and_store, calc_key
from app.store_chat import set_conversation
from app.services import tg_send_with_retry
from app.core.retry import with_retry
from app.http_client import get_http_client
from app.adapters.amo_client import AmoClient
from app.services.queue import rabbitmq
from app.events import UpdateStatus, UpdateStatusPayload

logger = logging.getLogger(__name__)


async def handle_mirror_amo_to_tg(payload: dict):
    """Переслать сообщение из AMO CRM пользователю Telegram.

    Args:
        payload: словарь с деталями сообщения. Ожидаются ключи
            ``bot_kind`` (``"master"`` или ``"operator"``) для выбора бота,
            ``user_id`` получателя, ``text`` с текстом и опциональный ``msg_key``
            для дедупликации.

    Поведение:
        Использует подходящего Telegram-бота для доставки текста. Если ``msg_key``
        уже обработан, сообщение пропускается.

    Returns:
        None
    """
    msg_key = payload.get("msg_key") or ""
    if msg_key:
        dedup = calc_key("mirror", msg_key)
        if not await check_and_store(dedup):
            logger.info("mirror: дубликат %s -> пропуск", dedup)
            return

    bot_kind = payload["bot_kind"]
    user_id = int(payload["user_id"])
    text = payload["text"]

    s = get_settings()
    token_field = (
        s.TELEGRAM_MASTER_BOT_TOKEN if bot_kind == "master" else s.TELEGRAM_OPERATOR_BOT_TOKEN
    )
    token = token_field.get_secret_value() if token_field else ""
    if not token:
        raise RuntimeError(f"Telegram bot '{bot_kind}' is not configured")

    async with Bot(token) as bot:
        await tg_send_with_retry(bot, user_id, text)


async def handle_mirror_tg_to_amo(payload: dict):
    """Отразить сообщение Telegram в AMO CRM.

    Args:
        payload: словарь с информацией о сообщении. Обязательные ключи:
            ``lead_id``, ``text``, ``tg_user_id`` и ``bot_kind``; необязательные —
            ``tg_user_name``, ``conversation_id`` и ``msg_key`` для дедупликации.

    Поведение:
        Добавляет сообщение как заметку в AMO и пересылает его через адаптер
        ``send_text_from_client``. Если возвращён новый идентификатор переписки,
        он сохраняется для последующего использования.

    Returns:
        None
    """
    msg_key = payload.get("msg_key") or ""
    if msg_key:
        dedup = calc_key("mirror", msg_key)
        if not await check_and_store(dedup):
            logger.info("mirror: дубликат %s -> пропуск", dedup)
            return

    lead_id = int(payload["lead_id"])
    text = payload["text"]
    tg_user_id = int(payload["tg_user_id"])
    tg_user_name = payload.get("tg_user_name")
    conv_id = payload.get("conversation_id")
    bot_kind_val = payload.get("bot_kind")
    if not isinstance(bot_kind_val, str):
        raise RuntimeError("bot_kind is required")
    bot_kind = bot_kind_val

    http_client = get_http_client()
    amo = await AmoClient.create(http_client)

    await with_retry(
        lambda: amo.add_note(lead_id, f"[TG->{bot_kind}] {text}"),
        attempts=6,
        is_retryable=lambda e: True,
    )

    new_cid = await with_retry(
        lambda: send_text_from_client(
            lead_id=lead_id,
            text=text,
            tg_user_id=tg_user_id,
            tg_user_name=tg_user_name,
            conversation_id=conv_id,
            client=http_client,
        ),
        attempts=6,
        is_retryable=lambda e: True,
    )
    if new_cid is not None and new_cid != conv_id:
        await set_conversation(tg_user_id, bot_kind, new_cid)


async def handle_mirror_bot_to_amo(payload: dict):
    """Переслать сгенерированное ботом сообщение в чат AMO.

    Args:
        payload: словарь, содержащий ``text`` и ``user_id``. Необязательные ключи:
            ``user_name``, ``conversation_id``, ``lead_id`` и ``msg_key`` для дедупликации.

    Поведение:
        Гарантирует существование беседы AMO для пользователя Telegram и
        отправляет текст как сообщение менеджера. Если ``msg_key`` уже
        обработан, дубликаты игнорируются.

    Returns:
        None
    """
    msg_key = payload.get("msg_key") or ""
    if msg_key:
        dedup = calc_key("mirror", msg_key)
        if not await check_and_store(dedup):
            logger.info("mirror: дубликат %s -> пропуск", dedup)
            return

    text = payload["text"]
    user_id = int(payload["user_id"])
    user_name = payload.get("user_name")
    conv_id = payload.get("conversation_id")
    lead_id = payload.get("lead_id")
    status_id = payload.get("status_id")

    http_client = get_http_client()
    text_sent = False

    if not conv_id and lead_id:

        amo = None
        try:
            amo = await AmoClient.create(http_client)
        except RuntimeError:
            logger.warning("токен Amo недоступен, пропускаю получение контакта")
        contact_id: int | None = None
        if amo is not None:
            try:
                lead = await amo.get_lead_with_contacts(int(lead_id))
                emb = (lead or {}).get("_embedded") or {}
                contacts = emb.get("contacts") or []
                if contacts:
                    contact_id = int(contacts[0]["id"])
            except Exception:
                logger.warning("не удалось получить контакт для лида %s", lead_id, exc_info=True)

        conv_id = await with_retry(
            lambda: ensure_chat_created(
                lead_id=int(lead_id),
                contact_id=contact_id,
                bind_contact_id=contact_id,
                tg_user_id=user_id,
                tg_user_name=user_name,
                client=http_client,
                init_text=text,
                init_as_manager=True,
            ),
            attempts=6,
            is_retryable=lambda e: True,
        )

        text_sent = True

        if status_id is not None:
            dedup = calc_key("chat_status", f"{lead_id}:{status_id}")
            if await check_and_store(dedup):
                event = UpdateStatus(
                    platform="amo",
                    action="amo_update_status",
                    payload=UpdateStatusPayload(
                        lead_id=int(lead_id),
                        status_id=int(status_id),
                        ts=int(time.time()),
                    ),
                )
                await rabbitmq.publish_task(event.model_dump(exclude_none=True))

    if not conv_id:
        raise RuntimeError("bot_to_amo: no conversation_id and no lead_id to create one")

    if not text_sent:
        lead_for_call = int(lead_id) if lead_id is not None else 0
        await with_retry(
            lambda: send_text_from_client(
                lead_id=lead_for_call,
                text=text,
                tg_user_id=user_id,
                tg_user_name=user_name,
                conversation_id=conv_id,
                client=http_client,
            ),
            attempts=6,
            is_retryable=lambda e: True,
                )

