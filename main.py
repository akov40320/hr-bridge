import asyncio
import contextlib
import logging
import uvicorn
from aiogram import Bot
from fastapi import FastAPI

from app.adapters.amochats import ensure_amo_chats_connected
from app.api import router, admin
from app.api.tasks import handle_task as _handle_task
from app.api.api_amochats import router_amo_chats, amo_admin
from app.bootstrap import ensure_tokens
from app.core.config import settings
from app.db import init_db
import time
from app.services.hh_mapping import load
from app.api.hh_webhooks import ensure_hh_webhook
from app.services.queue import publish_task, consume
from app.http_client import get_http_client, close_http_client
from app.api.tg_webhooks import router as tg_wh_router
from app.core.logging_setup import setup_logging
from app.db.token_store import DbTokenStore

log = logging.getLogger(__name__)

setup_logging("INFO")

app = FastAPI(title="Recruiting Bridge")
app.include_router(router)
app.include_router(admin)
app.include_router(router_amo_chats)
app.include_router(amo_admin)

if settings.TELEGRAM_WEBHOOK_MODE:
    app.include_router(tg_wh_router)


async def auto_register_telegram_webhooks() -> None:
    if not settings.TELEGRAM_WEBHOOK_MODE:
        log.info("TELEGRAM_WEBHOOK_MODE=false — пропускаю установку вебхуков")
        return

    base = (settings.TELEGRAM_WEBHOOK_BASE or "").rstrip("/")
    if not base:
        log.warning("TELEGRAM_WEBHOOK_BASE пуст — не могу поставить вебхуки")
        return

    secret = settings.TELEGRAM_WEBHOOK_SECRET or None
    allowed = ["message"]

    # master
    if settings.TELEGRAM_MASTER_BOT_TOKEN:
        try:
            async with Bot(settings.TELEGRAM_MASTER_BOT_TOKEN) as m_bot:
                await m_bot.set_webhook(
                    url=f"{base}/tg/webhook/master",
                    secret_token=secret,
                    allowed_updates=allowed,
                    drop_pending_updates=True,
                )
                info = await m_bot.get_webhook_info()
                log.info("Master webhook set -> %s (pending=%s)", info.url, info.pending_update_count)
        except Exception:
            log.exception("Failed to set master webhook")

    # operator
    if settings.TELEGRAM_OPERATOR_BOT_TOKEN:
        try:
            async with Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN) as o_bot:
                await o_bot.set_webhook(
                    url=f"{base}/tg/webhook/operator",
                    secret_token=secret,
                    allowed_updates=allowed,
                    drop_pending_updates=True,
                )
                info = await o_bot.get_webhook_info()
                log.info("Operator webhook set -> %s (pending=%s)", info.url, info.pending_update_count)
        except Exception:
            log.exception("Failed to set operator webhook")


@app.on_event("startup")
async def on_startup():
    app.state.http_client = get_http_client()

    await init_db()
    await ensure_tokens()
    try:
        from app.db.token_store import DbTokenStore
        from app.services.hh_mapping import load as load_hh_mapping

        amo_tok = await DbTokenStore("amo").load()
        if amo_tok and amo_tok.get("access_token") and int(amo_tok.get("expires_at", 0)) > int(time.time()) + 30:
            if not load_hh_mapping():
                await publish_task({"platform": "system", "action": "hh_autofill"})
                log.info("Queued hh_autofill on startup")
    except Exception:
        log.info("Amo token not ready on startup — hh_autofill will be queued after OAuth")

        # стартуем RMQ consumer
    try:
        app.state.rmq_task = asyncio.create_task(consume(_handle_task, max_attempts=10))
        log.info("RMQ consumer started")
    except Exception:
        log.exception("Failed to start RMQ consumer")

    client = app.state.http_client
    await ensure_hh_webhook(client)
    await auto_register_telegram_webhooks()
    await ensure_amo_chats_connected(log, client)


@app.on_event("shutdown")
async def on_shutdown():
    t = getattr(app.state, "rmq_task", None)
    if t:
        t.cancel()
        with contextlib.suppress(Exception):
            await t
    await close_http_client()


@app.get("/")
async def root():
    return {
        "ok": True,
        "service": "Recruiting Bridge",
        "mode": "webhook" if settings.TELEGRAM_WEBHOOK_MODE else "polling"
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
