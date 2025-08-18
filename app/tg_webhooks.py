from fastapi import APIRouter, Request, Response, Depends
from aiogram import Bot
from aiogram.types import Update
from app.config import settings
from app.guards import require_admin
from app.tg_bots import make_router

router = APIRouter()

# Один dp на каждого бота
master_bot = Bot(settings.TELEGRAM_MASTER_BOT_TOKEN) if settings.TELEGRAM_MASTER_BOT_TOKEN else None
operator_bot = Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN) if settings.TELEGRAM_OPERATOR_BOT_TOKEN else None

master_dp = make_router("master") if master_bot else None
operator_dp = make_router("operator") if operator_bot else None


@router.post("/tg/webhook/master")
async def tg_master_wh(request: Request):
    if not master_bot or not master_dp:
        return Response(status_code=503)
    if settings.TELEGRAM_WEBHOOK_SECRET and \
       request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.TELEGRAM_WEBHOOK_SECRET:
        return Response(status_code=401)
    upd = Update.model_validate(await request.json())
    await master_dp.feed_update(bot=master_bot, update=upd)
    return {"ok": True}



@router.post("/tg/webhook/operator")
async def tg_operator_wh(request: Request):
    if settings.TELEGRAM_WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.TELEGRAM_WEBHOOK_SECRET:
            return Response(status_code=401)
    data = await request.json()
    upd = Update.model_validate(data)
    await operator_dp.feed_update(bot=operator_bot, update=upd)
    return {"ok": True}


admin_tg = APIRouter(prefix="/admin/tg", dependencies=[Depends(require_admin)])


@admin_tg.post("/set-webhooks")
async def set_webhooks():
    base = settings.TELEGRAM_WEBHOOK_BASE.rstrip("/")
    secret = settings.TELEGRAM_WEBHOOK_SECRET or None
    out = {}

    if settings.TELEGRAM_MASTER_BOT_TOKEN:
        bot = Bot(settings.TELEGRAM_MASTER_BOT_TOKEN)
        ok = await bot.set_webhook(url=f"{base}/tg/webhook/master",
                                   secret_token=secret)
        out["master"] = ok

    if settings.TELEGRAM_OPERATOR_BOT_TOKEN:
        bot = Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN)
        ok = await bot.set_webhook(url=f"{base}/tg/webhook/operator",
                                   secret_token=secret)
        out["operator"] = ok

    return {"ok": True, "set": out}


@admin_tg.post("/delete-webhooks")
async def delete_webhooks():
    results = {}
    if master_bot:
        results["master"] = await master_bot.delete_webhook()
    if operator_bot:
        results["operator"] = await operator_bot.delete_webhook()
    return {"ok": True, "results": results}
