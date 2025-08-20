from __future__ import annotations
import asyncio, os, logging
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from httpx import HTTPStatusError, TimeoutException, ConnectError

from app.amochats import send_text_from_manager, ensure_chat_created, send_text_from_client
from app.config import settings
from app.dedup import check_and_store, calc_key
from app.queue import consume, publish_retry, publish_dlq
from app.adapters import hh as hh_adapt, avito as avito_adapt
from app.amo_client import AmoClient, ReauthRequired
from app.logging_setup import setup_logging
from app.store_chat import set_conversation

setup_logging("INFO")
logger = logging.getLogger(__name__)

WORKER_MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "6"))

# --- Reused Telegram bots (single instances) ---
master_bot = Bot(settings.TELEGRAM_MASTER_BOT_TOKEN) if settings.TELEGRAM_MASTER_BOT_TOKEN else None
operator_bot = Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN) if settings.TELEGRAM_OPERATOR_BOT_TOKEN else None

async def _tg_send_with_retry(bot: Bot, chat_id: int, text: str):
    backoff = 0.5
    for _ in range(7):
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            return
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramAPIError:
            if backoff > 8:
                raise
            await asyncio.sleep(backoff)
            backoff *= 2

async def _with_backoff(coro, *args, **kwargs):
    backoff = 0.5
    for _ in range(6):
        try:
            return await coro(*args, **kwargs)
        except Exception:
            if backoff > 8:
                raise
            await asyncio.sleep(backoff)
            backoff *= 2

def _is_transient(e: Exception) -> bool:
    if isinstance(e, (TimeoutException, ConnectError)):
        return True
    if isinstance(e, HTTPStatusError):
        return e.response.status_code == 429 or 500 <= e.response.status_code < 600
    return False

async def handle(payload: dict, attempts: int):
    try:
        plat = payload.get("platform"); act = payload.get("action")

        # --- Debug
        if plat == "debug" and act == "echo":
            logger.info("RMQ ECHO: %s", payload.get("msg"))
            return

        # --- Avito
        if plat == "avito" and act == "send_message":
            await avito_adapt.send_message(payload["external_id"], payload["text"], owner_id=payload.get("owner_id"))
            return

        if plat == "hh" and act == "set_state":
            await hh_adapt.set_employer_state(payload["external_id"], payload["target_state"], employer_id=payload.get("owner_id"))
            return

        if plat == "avito" and act == "mark_read":
            await avito_adapt.mark_read(payload["external_id"], owner_id=payload.get("owner_id"))
            return

        # --- Amo: вспомогательные
        if plat == "amo" and act == "amo_create_lead":
            amo = await AmoClient.create()
            await amo.create_leads(payload["lead_body"])
            return

        if plat == "amo" and act == "amo_add_note":
            amo = await AmoClient.create()
            await amo.add_note(int(payload["lead_id"]), payload["text"])
            return

        if plat == "amo" and act == "amo_add_tags":
            amo = await AmoClient.create()
            await amo.add_tags(int(payload["lead_id"]), list(payload.get("tags") or []))
            return

        # --- Mirroring
        if plat == "mirror":
            # идемпотентность для ретраев
            msg_key = (payload.get("msg_key") or "").encode("utf-8")
            if msg_key:
                dedup = calc_key("mirror", msg_key)
                if not await check_and_store(dedup):
                    logger.info("mirror: duplicate %s -> skip", dedup)
                    return

            if act == "amo_to_tg":
                # payload: bot_kind, user_id, text
                bot_kind = payload["bot_kind"]
                user_id = int(payload["user_id"])
                text = payload["text"]
                bot = master_bot if bot_kind == "master" else operator_bot
                if not bot:
                    raise RuntimeError(f"Telegram bot '{bot_kind}' is not configured")
                await _tg_send_with_retry(bot, user_id, text)
                return

            if act == "tg_to_amo":
                # payload: lead_id, text, tg_user_id, tg_user_name, conversation_id?, bot_kind
                lead_id = int(payload["lead_id"])
                text = payload["text"]
                tg_user_id = int(payload["tg_user_id"])
                tg_user_name = payload.get("tg_user_name")
                conv_id = payload.get("conversation_id")
                bot_kind = payload.get("bot_kind")

                amo = await AmoClient.create()
                await _with_backoff(amo.add_note, lead_id, f"[TG->{bot_kind}] {text}")

                new_cid = await _with_backoff(
                    send_text_from_client,
                    lead_id=lead_id,
                    text=text,
                    tg_user_id=tg_user_id,
                    tg_user_name=tg_user_name,
                    conversation_id=conv_id,
                )
                if new_cid and new_cid != conv_id:
                    await set_conversation(tg_user_id, bot_kind, new_cid)
                return

            if act == "bot_to_amo":
                # payload: text, user_id, user_name, conversation_id? or lead_id
                text = payload["text"]
                user_id = int(payload["user_id"])
                user_name = payload.get("user_name")
                conv_id = payload.get("conversation_id")
                lead_id = payload.get("lead_id")
                if not conv_id and lead_id:
                    conv_id = await _with_backoff(
                        ensure_chat_created,
                        lead_id=int(lead_id),
                        tg_user_id=user_id,
                        tg_user_name=user_name,
                    )
                if not conv_id:
                    raise RuntimeError("bot_to_amo: no conversation_id and no lead_id to create one")
                await _with_backoff(
                    send_text_from_manager,
                    conversation_id=conv_id,
                    user_id=user_id,
                    user_name=user_name,
                    avatar=None,
                    text=text,
                )
                return

        raise RuntimeError(f"unknown task: {payload}")

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
