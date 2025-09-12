"""Эндпоинты вебхуков Telegram.

Модуль предоставляет обработчики FastAPI, которые используют боты Telegram
для доставки обновлений вебхуков. Эти же обработчики применяются в тестах,
где объекты ботов передаются напрямую.
"""

import logging
from typing import cast

from fastapi import APIRouter, Request, Response, Depends
from aiogram import Bot
from aiogram.types import Update
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.guards import require_admin
from app.tg_router import make_router

logger = logging.getLogger("tg.webhooks")

settings = get_settings()  # модульный settings — тесты его тоже патчат
router = APIRouter()
admin_tg = APIRouter(prefix="/admin/tg", dependencies=[Depends(require_admin)])

# модульный tokens — тесты ожидают tg_webhooks.tokens
tokens: dict[str, object] = {
    "master": settings.TELEGRAM_MASTER_BOT_TOKEN,
    "operator": settings.TELEGRAM_OPERATOR_BOT_TOKEN,
}


def make_tg_webhook(key: object, kind: str | None = None):
    """
    key:
      - str -> имя ключа в tokens (прод)
      - object|None -> явный бот-объект (тесты). Если None — считаем, что бота нет и возвращаем 503.
    """
    async def _handler(request: Request):
        # 1) секрет проверяем первым
        secret_hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if settings.TELEGRAM_WEBHOOK_SECRET and secret_hdr != settings.TELEGRAM_WEBHOOK_SECRET:
            logger.warning("%s webhook: неверный секрет -> 401", kind or key)
            return Response(status_code=401)

        # 2) парсим апдейт
        try:
            payload = await request.json()
            upd = Update.model_validate(payload)
        except (ValueError, ValidationError):
            logger.exception("%s webhook: некорректный json/update", kind or key)
            return Response(status_code=400)

        dp = make_router(kind or (key if isinstance(key, str) else "master"))

        # 3) режим: явный бот vs токен из settings
        if not isinstance(key, str):
            # Явно переданный бот-объект (тестовый путь)
            if key is None:
                logger.warning("%s webhook вызван, но бот отсутствует -> 503", kind or "unknown")
                return Response(status_code=503)
            await dp.feed_update(bot=cast(Bot, key), update=upd)
        else:
            # Продовый путь по токену
            token = tokens.get(key)
            if not isinstance(token, str) or not token:
                logger.warning("%s webhook вызван, но токен пуст -> 503", key)
                return Response(status_code=503)
            async with Bot(token) as bot:
                await dp.feed_update(bot=bot, update=upd)

        logger.info("%s вебхук ok: update_id=%s", kind or key, getattr(upd, "update_id", None))
        return {"ok": True}

    return _handler




# Продовая регистрация — через строковые ключи
for _kind in ("master", "operator"):
    router.post(f"/tg/webhook/{_kind}")(make_tg_webhook(_kind, _kind))


@admin_tg.post("/set-webhooks")
async def set_webhooks():
    """Зарегистрировать вебхуки для всех настроенных ботов."""
    base = (settings.TELEGRAM_WEBHOOK_BASE or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "TELEGRAM_WEBHOOK_BASE is empty"}
    secret = settings.TELEGRAM_WEBHOOK_SECRET or None
    allowed = ["message"]

    out = {}
    for kind, value in tokens.items():
        if isinstance(value, str) and value:
            async with Bot(value) as bot:
                out[kind] = await bot.set_webhook(
                    url=f"{base}/tg/webhook/{kind}",
                    secret_token=secret,
                    allowed_updates=allowed,
                    drop_pending_updates=True,
                )
    return {"ok": True, "set": out}


@admin_tg.post("/delete-webhooks")
async def delete_webhooks():
    """Удалить вебхуки для всех настроенных ботов."""
    results = {}
    for kind, value in tokens.items():
        if isinstance(value, str) and value:
            async with Bot(value) as bot:
                results[kind] = await bot.delete_webhook(drop_pending_updates=True)
    return {"ok": True, "results": results}


@admin_tg.get("/webhook-info")
async def webhook_info():
    """Получить информацию о вебхуках для всех настроенных ботов."""
    res = {}
    for kind, value in tokens.items():
        if isinstance(value, str) and value:
            async with Bot(value) as bot:
                res[kind] = await bot.get_webhook_info()
    return {"ok": True, "info": res}
