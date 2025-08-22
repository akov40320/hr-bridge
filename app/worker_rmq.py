from __future__ import annotations
import asyncio, os, logging
from aiogram import Bot
from httpx import HTTPStatusError, TimeoutException, ConnectError

from app.amochats import send_text_from_manager, ensure_chat_created, send_text_from_client
from app.config import settings
from app.dedup import check_and_store, calc_key
from app.queue import consume, publish_retry, publish_dlq
from app.adapters import hh as hh_adapt, avito as avito_adapt
from app.amo_client import AmoClient, ReauthRequired
from app.logging_setup import setup_logging
from app.store_chat import set_conversation
from app.services import tg_send_with_retry, with_backoff
from app.http_client import get_http_client

setup_logging("INFO")
logger = logging.getLogger(__name__)

WORKER_MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "6"))

# --- Reused Telegram bots (single instances) ---
master_bot = Bot(settings.TELEGRAM_MASTER_BOT_TOKEN) if settings.TELEGRAM_MASTER_BOT_TOKEN else None
operator_bot = Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN) if settings.TELEGRAM_OPERATOR_BOT_TOKEN else None


def _is_transient(e: Exception) -> bool:
    if isinstance(e, (TimeoutException, ConnectError)):
        return True
    if isinstance(e, HTTPStatusError):
        return e.response.status_code == 429 or 500 <= e.response.status_code < 600
    return False


async def handle_hh_send_message(payload: dict):
    logger.info("hh.send_message: %s", payload.get("external_id"))
    client = get_http_client()
    await hh_adapt.send_message(
        payload["external_id"],
        payload["text"],
        employer_id=payload.get("owner_id"),
        client=client,
    )


async def handle_hh_set_state(payload: dict):
    logger.info(
        "hh.set_state: %s -> %s",
        payload.get("external_id"),
        payload.get("target_state"),
    )
    client = get_http_client()
    await hh_adapt.set_employer_state(
        payload["external_id"],
        payload["target_state"],
        employer_id=payload.get("owner_id"),
        client=client,
    )


async def handle_debug_echo(payload: dict):
    logger.info("RMQ ECHO: %s", payload.get("msg"))


async def handle_avito_send_message(payload: dict):
    logger.info("avito.send_message: %s", payload.get("external_id"))
    client = get_http_client()
    await avito_adapt.send_message(
        payload["external_id"],
        payload["text"],
        owner_id=payload.get("owner_id"),
        client=client,
    )


async def handle_avito_mark_read(payload: dict):
    logger.info("avito.mark_read: %s", payload.get("external_id"))
    await avito_adapt.mark_read(
        payload["external_id"],
        owner_id=payload.get("owner_id"),
        client=get_http_client(),
    )


async def handle_amo_create_lead(payload: dict):
    logger.info("amo.create_lead")
    amo = await AmoClient.create(get_http_client())
    await amo.create_leads(payload["lead_body"])


async def handle_amo_add_note(payload: dict):
    logger.info("amo.add_note: %s", payload.get("lead_id"))
    amo = await AmoClient.create(get_http_client())
    await amo.add_note(int(payload["lead_id"]), payload["text"])


async def handle_amo_add_tags(payload: dict):
    logger.info("amo.add_tags: %s", payload.get("lead_id"))
    amo = await AmoClient.create(get_http_client())
    await amo.add_tags(int(payload["lead_id"]), list(payload.get("tags") or []))


async def handle_mirror_amo_to_tg(payload: dict):
    msg_key = (payload.get("msg_key") or "").encode("utf-8")
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
    msg_key = (payload.get("msg_key") or "").encode("utf-8")
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
    await with_backoff(amo.add_note, lead_id, f"[TG->{bot_kind}] {text}")
    client = get_http_client()
    new_cid = await with_backoff(
        send_text_from_client,
        lead_id=lead_id,
        text=text,
        tg_user_id=tg_user_id,
        tg_user_name=tg_user_name,
        conversation_id=conv_id,
        client=client,
    )
    if new_cid and new_cid != conv_id:
        await set_conversation(tg_user_id, bot_kind, new_cid)


async def handle_mirror_bot_to_amo(payload: dict):
    msg_key = (payload.get("msg_key") or "").encode("utf-8")
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
        conv_id = await with_backoff(
            ensure_chat_created,
            lead_id=int(lead_id),
            tg_user_id=user_id,
            tg_user_name=user_name,
            client=get_http_client(),
        )
    if not conv_id:
        raise RuntimeError("bot_to_amo: no conversation_id and no lead_id to create one")
    await with_backoff(
        send_text_from_manager,
        conversation_id=conv_id,
        user_id=user_id,
        user_name=user_name,
        avatar=None,
        text=text,
        client=get_http_client(),
    )


HANDLERS = {
    ("hh", "send_message"): handle_hh_send_message,
    ("hh", "set_state"): handle_hh_set_state,
    ("debug", "echo"): handle_debug_echo,
    ("avito", "send_message"): handle_avito_send_message,
    ("avito", "mark_read"): handle_avito_mark_read,
    ("amo", "amo_create_lead"): handle_amo_create_lead,
    ("amo", "amo_add_note"): handle_amo_add_note,
    ("amo", "amo_add_tags"): handle_amo_add_tags,
    ("mirror", "amo_to_tg"): handle_mirror_amo_to_tg,
    ("mirror", "tg_to_amo"): handle_mirror_tg_to_amo,
    ("mirror", "bot_to_amo"): handle_mirror_bot_to_amo,
}


async def handle(payload: dict, attempts: int):
    try:
        plat = payload.get("platform")
        act = payload.get("action")
        handler = HANDLERS.get((plat, act))
        if not handler:
            raise RuntimeError(f"unknown task: {payload}")
        await handler(payload)

    except ReauthRequired as e:
        logger.warning("ReauthRequired: %s", e)
        await publish_dlq(payload, attempts + 1, f"ReauthRequired: {e}")

    except Exception as e:
        if _is_transient(e) and attempts + 1 < WORKER_MAX_ATTEMPTS:
            await publish_retry(payload, attempts + 1)
        else:
            logger.exception("Task failed terminally")
            await publish_dlq(payload, attempts + 1, str(e))


async def run_forever():
    await consume(handle)


if __name__ == "__main__":
    asyncio.run(run_forever())
