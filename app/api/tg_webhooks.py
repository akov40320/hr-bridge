import logging
from fastapi import APIRouter, Request, Response, Depends
from aiogram import Bot
from aiogram.types import Update
from app.core.config import get_settings
from app.core.guards import require_admin
from app.tg_router import make_router

logger = logging.getLogger("tg.webhooks")
settings = get_settings()
router = APIRouter()


def make_tg_webhook(bot: Bot | None, kind: str):
    """Фабрика обработчиков Telegram вебхуков."""
    dp = make_router(kind) if bot else None

    async def _handler(request: Request):
        if not bot or not dp:
            logger.warning("%s webhook called, but bot or dp is None -> 503", kind)
            return Response(status_code=503)

        if settings.TELEGRAM_WEBHOOK_SECRET and \
           request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.TELEGRAM_WEBHOOK_SECRET:
            logger.warning("%s webhook: bad secret -> 401", kind)
            return Response(status_code=401)

        try:
            payload = await request.json()
            upd = Update.model_validate(payload)
        except Exception:
            logger.exception("%s webhook: invalid json/update", kind)
            return Response(status_code=400)

        await dp.feed_update(bot=bot, update=upd)
        logger.info("%s webhook ok: update_id=%s", kind, getattr(upd, "update_id", None))
        return {"ok": True}

    return _handler


tokens = {
    "master": settings.TELEGRAM_MASTER_BOT_TOKEN,
    "operator": settings.TELEGRAM_OPERATOR_BOT_TOKEN,
}

bots = {k: Bot(t) if t else None for k, t in tokens.items()}

for kind, bot in bots.items():
    router.post(f"/tg/webhook/{kind}")(make_tg_webhook(bot, kind))


admin_tg = APIRouter(prefix="/admin/tg", dependencies=[Depends(require_admin)])


@admin_tg.post("/set-webhooks")
async def set_webhooks():
    base = (settings.TELEGRAM_WEBHOOK_BASE or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "TELEGRAM_WEBHOOK_BASE is empty"}
    secret = settings.TELEGRAM_WEBHOOK_SECRET or None
    allowed = ["message"]
    out = {}

    for kind, token in tokens.items():
        if token:
            async with Bot(token) as bot:
                out[kind] = await bot.set_webhook(
                    url=f"{base}/tg/webhook/{kind}",
                    secret_token=secret,
                    allowed_updates=allowed,
                    drop_pending_updates=True,
                )

    return {"ok": True, "set": out}


@admin_tg.post("/delete-webhooks")
async def delete_webhooks():
    results = {}
    for kind, token in tokens.items():
        if token:
            async with Bot(token) as bot:
                results[kind] = await bot.delete_webhook(drop_pending_updates=True)
    return {"ok": True, "results": results}


@admin_tg.get("/webhook-info")
async def webhook_info():
    res = {}
    for kind, token in tokens.items():
        if token:
            async with Bot(token) as bot:
                res[kind] = await bot.get_webhook_info()
    return {"ok": True, "info": res}
