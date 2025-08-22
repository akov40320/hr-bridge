import logging
from aiogram import Bot

from app.amochats import send_text_from_manager, ensure_chat_created, send_text_from_client
from app.config import settings
from app.services.dedup import check_and_store, calc_key
from app.store_chat import set_conversation
from app.services import tg_send_with_retry
from app.core.retry import with_retry
from app.http_client import get_http_client
from app.adapters.amo_client import AmoClient

logger = logging.getLogger(__name__)

master_bot = Bot(settings.TELEGRAM_MASTER_BOT_TOKEN) if settings.TELEGRAM_MASTER_BOT_TOKEN else None
operator_bot = Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN) if settings.TELEGRAM_OPERATOR_BOT_TOKEN else None


async def handle_mirror_amo_to_tg(payload: dict):
    msg_key = payload.get("msg_key") or ""
    if msg_key:
        dedup = calc_key("mirror", msg_key)
        if not await check_and_store(dedup):
            logger.info("mirror: duplicate %s -> skip", dedup)
            return
    bot_kind = payload["bot_kind"]
    user_id = int(payload["user_id"])
    text = payload["text"]
    bot = master_bot if bot_kind == "master" else operator_bot
    if not bot:
        raise RuntimeError(f"Telegram bot '{bot_kind}' is not configured")
    await tg_send_with_retry(bot, user_id, text)


async def handle_mirror_tg_to_amo(payload: dict):
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
    bot_kind = payload.get("bot_kind")
    amo = await AmoClient.create(get_http_client())
    await with_retry(
        lambda: amo.add_note(lead_id, f"[TG->{bot_kind}] {text}"),
        attempts=6,
        is_retryable=lambda e: True,
    )
    client = get_http_client()
    new_cid = await with_retry(
        lambda: send_text_from_client(
            lead_id=lead_id,
            text=text,
            tg_user_id=tg_user_id,
            tg_user_name=tg_user_name,
            conversation_id=conv_id,
            client=client,
        ),
        attempts=6,
        is_retryable=lambda e: True,
    )
    if new_cid and new_cid != conv_id:
        await set_conversation(tg_user_id, bot_kind, new_cid)


async def handle_mirror_bot_to_amo(payload: dict):
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
    if not conv_id and lead_id:
        conv_id = await with_retry(
            lambda: ensure_chat_created(
                lead_id=int(lead_id),
                tg_user_id=user_id,
                tg_user_name=user_name,
                client=get_http_client(),
            ),
            attempts=6,
            is_retryable=lambda e: True,
        )
    if not conv_id:
        raise RuntimeError("bot_to_amo: no conversation_id and no lead_id to create one")
    await with_retry(
        lambda: send_text_from_manager(
            conversation_id=conv_id,
            user_id=user_id,
            user_name=user_name,
            avatar=None,
            text=text,
            client=get_http_client(),
        ),
        attempts=6,
        is_retryable=lambda e: True,
    )
