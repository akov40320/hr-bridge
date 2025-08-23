import asyncio
import contextlib
import logging
import time

import uvicorn
from aiogram import Bot
from fastapi import FastAPI, Depends, APIRouter

from app.adapters.amochats import ensure_amo_chats_connected
from app.api import oauth, admin as admin_module, hh_incoming, avito_incoming, amo_webhooks
from app.api.api_amochats import router_amo_chats, amo_admin
from app.api.hh_webhooks import ensure_hh_webhook
from app.api.tg_webhooks import router as tg_wh_router
from app.api.tasks import handle_task as _handle_task
from app.bootstrap import ensure_tokens
from app.core.config import get_settings
from app.core.guards import require_admin
from app.core.logging_setup import setup_logging
from app.core.middleware import LoggingMiddleware, metrics_endpoint
from app.db import init_db
from app.http_client import get_http_client, close_http_client
from app.services.queue import rabbitmq

log = logging.getLogger(__name__)
setup_logging("INFO")

app = FastAPI(title="Recruiting Bridge")
app.add_middleware(LoggingMiddleware)
app.add_route("/metrics", metrics_endpoint)

# Собираем публичные роуты тут (без агрегирующего импорта пакета app.api)
public_router = APIRouter()
public_router.include_router(oauth.router)
public_router.include_router(hh_incoming.router)
public_router.include_router(avito_incoming.router)
public_router.include_router(amo_webhooks.router)
public_router.include_router(admin_module.router)

admin_router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
admin_router.include_router(admin_module.admin)

app.include_router(public_router)
app.include_router(admin_router)
app.include_router(router_amo_chats)
app.include_router(amo_admin)
app.include_router(tg_wh_router)


async def auto_register_telegram_webhooks() -> None:
    s = get_settings()
    base = (s.TELEGRAM_WEBHOOK_BASE or "").rstrip("/")
    if not base:
        log.warning("TELEGRAM_WEBHOOK_BASE пуст — не могу поставить вебхуки")
        return

    secret = s.TELEGRAM_WEBHOOK_SECRET or None
    allowed = ["message"]

    # master
    if s.TELEGRAM_MASTER_BOT_TOKEN:
        try:
            async with Bot(s.TELEGRAM_MASTER_BOT_TOKEN) as m_bot:
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
    if s.TELEGRAM_OPERATOR_BOT_TOKEN:
        try:
            async with Bot(s.TELEGRAM_OPERATOR_BOT_TOKEN) as o_bot:
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
    s = get_settings()
    s.validate_required()

    await init_db()
    await ensure_tokens()
    await rabbitmq.connect()

    try:
        from app.db.token_store import DbTokenStore
        from app.services.hh_mapping import load as load_hh_mapping

        amo_tok = await DbTokenStore("amo").load()
        if amo_tok and amo_tok.get("access_token") and int(amo_tok.get("expires_at", 0)) > int(time.time()) + 30:
            if not load_hh_mapping():
                await rabbitmq.publish_task({"platform": "system", "action": "hh_autofill"})
                log.info("Queued hh_autofill on startup")
    except Exception:
        log.info("Amo token not ready on startup — hh_autofill will be queued after OAuth")

    # стартуем RMQ consumer
    try:
        app.state.rmq_task = asyncio.create_task(rabbitmq.consume(_handle_task, max_attempts=10))
        log.info("RMQ consumer started")
    except Exception:
        log.exception("Failed to start RMQ consumer")

    client = get_http_client()
    await ensure_hh_webhook(client)
    await auto_register_telegram_webhooks()
    await ensure_amo_chats_connected(log, client)


@app.on_event("shutdown")
async def on_shutdown():
    t = getattr(app.state, "rmq_task", None)
    if t:
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
    await rabbitmq.close()
    await close_http_client()


@app.get("/")
async def root(s = Depends(get_settings)):
    return {
        "ok": True,
        "service": "Recruiting Bridge",
        "mode": "webhook" if s.TELEGRAM_WEBHOOK_MODE else "polling",
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
