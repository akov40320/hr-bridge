import logging
from fastapi import APIRouter, Request, Response, Depends
from aiogram import Bot
from aiogram.types import Update
from app.config import settings
from app.guards import require_admin
from app.tg_router import make_router

logger = logging.getLogger("tg.webhooks")

router = APIRouter()

# Делаем «долгоживущие» инстансы ботов и диспетчеров (не создаём на каждый запрос)
master_bot = Bot(settings.TELEGRAM_MASTER_BOT_TOKEN) if settings.TELEGRAM_MASTER_BOT_TOKEN else None
operator_bot = Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN) if settings.TELEGRAM_OPERATOR_BOT_TOKEN else None

master_dp = make_router("master") if master_bot else None
operator_dp = make_router("operator") if operator_bot else None


@router.post("/tg/webhook/master")
async def tg_master_wh(request: Request):
    if not master_bot or not master_dp:
        logger.warning("master webhook called, but bot or dp is None -> 503")
        return Response(status_code=503)

    if settings.TELEGRAM_WEBHOOK_SECRET and \
       request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.TELEGRAM_WEBHOOK_SECRET:
        logger.warning("master webhook: bad secret -> 401")
        return Response(status_code=401)

    try:
        payload = await request.json()
        upd = Update.model_validate(payload)
    except Exception as e:
        logger.exception("master webhook: invalid json/update")
        return Response(status_code=400)

    await master_dp.feed_update(bot=master_bot, update=upd)
    logger.info("master webhook ok: update_id=%s", getattr(upd, "update_id", None))
    return {"ok": True}


@router.post("/tg/webhook/operator")
async def tg_operator_wh(request: Request):
    if not operator_bot or not operator_dp:
        logger.warning("operator webhook called, but bot or dp is None -> 503")
        return Response(status_code=503)

    if settings.TELEGRAM_WEBHOOK_SECRET and \
       request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.TELEGRAM_WEBHOOK_SECRET:
        logger.warning("operator webhook: bad secret -> 401")
        return Response(status_code=401)

    try:
        payload = await request.json()
        upd = Update.model_validate(payload)
    except Exception:
        logger.exception("operator webhook: invalid json/update")
        return Response(status_code=400)

    await operator_dp.feed_update(bot=operator_bot, update=upd)
    logger.info("operator webhook ok: update_id=%s", getattr(upd, "update_id", None))
    return {"ok": True}


admin_tg = APIRouter(prefix="/admin/tg", dependencies=[Depends(require_admin)])


@admin_tg.post("/set-webhooks")
async def set_webhooks():
    base = (settings.TELEGRAM_WEBHOOK_BASE or "").rstrip("/")
    if not base:
        logger.error("set-webhooks: TELEGRAM_WEBHOOK_BASE is empty")
        return {"ok": False, "error": "TELEGRAM_WEBHOOK_BASE is empty"}

    secret = settings.TELEGRAM_WEBHOOK_SECRET or None
    allowed = ["message"]  # добавишь "callback_query" при необходимости
    out = {}

    if master_bot:
        out["master"] = await master_bot.set_webhook(
            url=f"{base}/tg/webhook/master",
            secret_token=secret,
            allowed_updates=allowed,
            drop_pending_updates=True,
        )
        logger.info("set_webhook master -> %s", out["master"])
    if operator_bot:
        out["operator"] = await operator_bot.set_webhook(
            url=f"{base}/tg/webhook/operator",
            secret_token=secret,
            allowed_updates=allowed,
            drop_pending_updates=True,
        )
        logger.info("set_webhook operator -> %s", out["operator"])

    return {"ok": True, "set": out}


@admin_tg.post("/delete-webhooks")
async def delete_webhooks():
    results = {}
    if master_bot:
        results["master"] = await master_bot.delete_webhook()
        logger.info("delete_webhook master -> %s", results["master"])
    if operator_bot:
        results["operator"] = await operator_bot.delete_webhook()
        logger.info("delete_webhook operator -> %s", results["operator"])
    return {"ok": True, "results": results}


@admin_tg.get("/webhook-info")
async def webhook_info():
    res = {}
    if master_bot:
        res["master"] = await master_bot.get_webhook_info()
    if operator_bot:
        res["operator"] = await operator_bot.get_webhook_info()
    logger.info("webhook-info -> keys=%s", list(res.keys()))
    return {"ok": True, "info": res}
