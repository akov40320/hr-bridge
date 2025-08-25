"""Handlers that mirror messages between AMO CRM and Telegram bots.

This module provides asynchronous worker handlers used to forward messages
from AMO CRM to Telegram chats, relay Telegram messages back to AMO, and send
bot-generated messages into AMO chats. All handlers accept a ``payload``
dictionary with details specific to the direction of the mirror.
"""

import logging
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

logger = logging.getLogger(__name__)


async def handle_mirror_amo_to_tg(payload: dict):
    """Forward a message from AMO CRM to a Telegram user.

    Args:
        payload: Mapping containing message details. Expected keys are
            ``bot_kind`` (``"master"`` or ``"operator"``) to choose a bot,
            ``user_id`` for the Telegram recipient, ``text`` with the message
            body and optional ``msg_key`` used for deduplication.

    Behaviour:
        Uses the appropriate Telegram bot to deliver the text. When ``msg_key``
        is provided and already processed, the message is skipped.

    Returns:
        None
    """
    msg_key = payload.get("msg_key") or ""
    if msg_key:
        dedup = calc_key("mirror", msg_key)
        if not await check_and_store(dedup):
            logger.info("mirror: duplicate %s -> skip", dedup)
            return

    bot_kind = payload["bot_kind"]
    user_id = int(payload["user_id"])
    text = payload["text"]

    s = get_settings()
    token = s.TELEGRAM_MASTER_BOT_TOKEN if bot_kind == "master" else s.TELEGRAM_OPERATOR_BOT_TOKEN
    if not token:
        raise RuntimeError(f"Telegram bot '{bot_kind}' is not configured")

    async with Bot(token) as bot:
        await tg_send_with_retry(bot, user_id, text)


async def handle_mirror_tg_to_amo(payload: dict):
    """Mirror a Telegram message into AMO CRM (with safe chat attach)."""
    msg_key = payload.get("msg_key") or ""
    if msg_key:
        dedup = calc_key("mirror", msg_key)
        if not await check_and_store(dedup):
            logger.info("mirror: duplicate %s -> skip", dedup)
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

    # лог в ленте
    await with_retry(lambda: amo.add_note(lead_id, f"[TG->{bot_kind}] {text}"), attempts=6, is_retryable=lambda e: True)

    # гарантируем, что чат создан и ПРИВЯЗАН к контакту до отправки сообщения
    if not conv_id:
        lead = await amo.get_lead(int(lead_id))
        main_contact_id = (((lead.get("_embedded") or {}).get("contacts")) or [{}])[0].get("id")

        conv_id, amo_uuid = await ensure_chat_created(
            lead_id=int(lead_id),
            tg_user_id=tg_user_id,
            tg_user_name=tg_user_name,
            client=http_client,
            contact_id=main_contact_id,
        )
        if main_contact_id and amo_uuid:
            await amo.attach_chat_to_contact(int(main_contact_id), amo_uuid)

    # теперь безопасно отправляем
    await with_retry(
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



async def handle_mirror_bot_to_amo(payload: dict):
    """Forward a bot-generated message to AMO chat (attach before send)."""
    msg_key = payload.get("msg_key") or ""
    if msg_key:
        dedup = calc_key("mirror", msg_key)
        if not await check_and_store(dedup):
            logger.info("mirror: duplicate %s -> skip", dedup)
            return

    text = payload["text"]
    user_id = int(payload["user_id"])
    user_name = payload.get("user_name")
    conv_id = payload.get("conversation_id")
    lead_id = payload.get("lead_id")
    status_id = payload.get("status_id")

    if not lead_id:
        raise RuntimeError("bot_to_amo: lead_id is required to create/attach chat")

    http_client = get_http_client()
    amo = await AmoClient.create(http_client)

    # основной контакт сделки
    lead = await amo.get_lead(int(lead_id))
    main_contact_id = (((lead.get("_embedded") or {}).get("contacts")) or [{}])[0].get("id")

    # создать чат, получить uuid, привязать к контакту
    if not conv_id:
        conv_id, amo_uuid = await ensure_chat_created(
            lead_id=int(lead_id),
            tg_user_id=user_id,
            tg_user_name=user_name,
            client=http_client,
            contact_id=main_contact_id,
        )
        if main_contact_id and amo_uuid:
            await amo.attach_chat_to_contact(int(main_contact_id), amo_uuid)

        # опционально сменить статус после первой инициализации
        if status_id is not None:
            dedup = calc_key("chat_status", f"{lead_id}:{status_id}")
            if await check_and_store(dedup):
                await rabbitmq.publish_task({
                    "platform": "amo",
                    "action": "amo_update_status",
                    "lead_id": int(lead_id),
                    "status_id": int(status_id),
                })

    # отправить сообщение после привязки
    await with_retry(
        lambda: send_text_from_client(
            lead_id=int(lead_id),
            text=text,
            tg_user_id=user_id,
            tg_user_name=user_name,
            conversation_id=conv_id,
            client=http_client,
        ),
        attempts=6,
        is_retryable=lambda e: True,
    )
