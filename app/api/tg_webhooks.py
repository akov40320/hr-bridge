import logging
from fastapi import APIRouter, Request, Response, Depends
from aiogram import Bot
from aiogram.types import Update

from app.core.config import get_settings
from app.core.guards import require_admin
from app.tg_router import make_router

logger = logging.getLogger("tg.webhooks")

router = APIRouter()
admin_tg = APIRouter(prefix="/admin/tg", dependencies=[Depends(require_admin)])


def make_tg_webhook(kind: str):
    """Фабрика обработчиков Telegram вебхуков с ленивой инициализацией Bot и настроек."""
    async def _handler(request: Request):
        s = get_settings()
        if kind == "master":
            token = s.TELEGRAM_MASTER_BOT_TOKEN
        elif kind == "operator":
            token = s.TELEGRAM_OPERATOR_BOT_TOKEN
        else:
            token = None

        if not token:
            logger.warning("%s webhook called, but token is empty -> 503", kind)
            return Response(status_code=503)

        # Секрет проверяем из настроек на каждый запрос
        secret_hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if s.TELEGRAM_WEBHOOK_SECRET and secret_hdr != s.TELEGRAM_WEBHOOK_SECRET:
            logger.warning("%s webhook: bad secret -> 401", kind)
            return Response(status_code=401)

        try:
            payload = await request.json()
            upd = Update.model_validate(payload)
        except Exception:
            logger.exception("%s webhook: invalid json/update", kind)
            return Response(status_code=400)

        dp = make_router(kind)
        async with Bot(token) as bot:
            await dp.feed_update(bot=bot, update=upd)

        logger.info("%s webhook ok: update_id=%s", kind, getattr(upd, "update_id", None))
        return {"ok": True}

    return _handler


# Регистрация эндпоинтов (без чтения настроек на уровне модуля)
for _kind in ("master", "operator"):
    router.post(f"/tg/webhook/{_kind}")(make_tg_webhook(_kind))


@admin_tg.post("/set-webhooks")
async def set_webhooks():
    s = get_settings()
    base = (s.TELEGRAM_WEBHOOK_BASE or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "TELEGRAM_WEBHOOK_BASE is empty"}
    secret = s.TELEGRAM_WEBHOOK_SECRET or None
    allowed = ["message"]

    out = {}
    tokens = {
        "master": s.TELEGRAM_MASTER_BOT_TOKEN,
        "operator": s.TELEGRAM_OPERATOR_BOT_TOKEN,
    }
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
    s = get_settings()
    tokens = {
        "master": s.TELEGRAM_MASTER_BOT_TOKEN,
        "operator": s.TELEGRAM_OPERATOR_BOT_TOKEN,
    }

    results = {}
    for kind, token in tokens.items():
        if token:
            async with Bot(token) as bot:
                results[kind] = await bot.delete_webhook(drop_pending_updates=True)
    return {"ok": True, "results": results}


@admin_tg.get("/webhook-info")
async def webhook_info():
    s = get_settings()
    tokens = {
        "master": s.TELEGRAM_MASTER_BOT_TOKEN,
        "operator": s.TELEGRAM_OPERATOR_BOT_TOKEN,
    }

    res = {}
    for kind, token in tokens.items():
        if token:
            async with Bot(token) as bot:
                res[kind] = await bot.get_webhook_info()
    return {"ok": True, "info": res}
