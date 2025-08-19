import contextlib
import logging
import uvicorn
from aiogram import Bot
from fastapi import FastAPI
from app.api import router, admin
from app.api_amochats import router_amo_chats
from app.bootstrap import ensure_tokens
from app.config import settings
from app.db import init_db
from app.tg_webhooks import router as tg_wh_router
from app.logging_setup import setup_logging

log = logging.getLogger(__name__)

setup_logging("INFO")

app = FastAPI(title="Recruiting Bridge")
app.include_router(router)
app.include_router(admin)
app.include_router(router_amo_chats)

if settings.TELEGRAM_WEBHOOK_MODE:
    app.include_router(tg_wh_router)


async def auto_register_telegram_webhooks() -> None:
    """Ставит вебхуки для обоих ботов при старте, если включен режим вебхуков."""
    if not settings.TELEGRAM_WEBHOOK_MODE:
        log.info("TELEGRAM_WEBHOOK_MODE=false — автоустановка вебхуков пропущена")
        return

    base = (settings.TELEGRAM_WEBHOOK_BASE or "").rstrip("/")
    if not base:
        log.warning("TELEGRAM_WEBHOOK_BASE пуст — не могу поставить вебхуки")
        return

    secret = settings.TELEGRAM_WEBHOOK_SECRET or None
    allowed = ["message"]  # по нужде добавишь другие типы

    # master
    if settings.TELEGRAM_MASTER_BOT_TOKEN:
        try:
            m_bot = Bot(settings.TELEGRAM_MASTER_BOT_TOKEN)
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
            o_bot = Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN)
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
    await init_db()
    await ensure_tokens()
    await auto_register_telegram_webhooks()


@app.on_event("shutdown")
async def on_shutdown():
    t = getattr(app.state, "rmq_task", None)
    if t:
        t.cancel()
        with contextlib.suppress(Exception):
            await t


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
