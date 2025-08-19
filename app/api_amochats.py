import logging
from fastapi import APIRouter, Request, Response
from app.dedup import calc_key, check_and_store
from app.store_chat import get_by_lead, get_by_conversation
from aiogram import Bot
from app.config import settings

logger = logging.getLogger(__name__)
router_amo_chats = APIRouter()

# Боты для ответной пересылки в TG (если хочешь форвардить в обе группы ботов)
tg_master = Bot(settings.TELEGRAM_MASTER_BOT_TOKEN) if settings.TELEGRAM_MASTER_BOT_TOKEN else None
tg_operator = Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN) if settings.TELEGRAM_OPERATOR_BOT_TOKEN else None


@router_amo_chats.post("/webhooks/amo-chats/in")
async def amochats_in(request: Request):
    if settings.AMOCHATS_INCOMING_SECRET:
        if request.headers.get("X-AmoChats-Signature") != settings.AMOCHATS_INCOMING_SECRET:
            return Response(status_code=401)

    raw = await request.body()
    key = calc_key("amo_chats", raw)
    if not await check_and_store(key):
        logger.info("amo-chats duplicate webhook skipped")
        return {"ok": True, "duplicate": True}

    try:
        data = await request.json()
    except Exception:
        logger.warning("amo-chats bad json")
        return {"ok": False, "error": "bad json"}

    if data.get("event_type") != "new_message":
        return {"ok": True}

    payload = data.get("payload") or {}
    msg = (payload.get("message") or {})
    text = msg.get("text") or ""
    if not text:
        return {"ok": True}

    conv = (payload.get("conversation") or {})
    conv_uuid = conv.get("uuid")
    conv_ref = conv.get("ref_id") or conv.get("conversation_ref_id")

    lead_id = None
    if conv_ref and isinstance(conv_ref, str) and conv_ref.startswith("lead:"):
        try:
            lead_id = int(conv_ref.split(":", 1)[1])
        except Exception:
            lead_id = None

    links = []
    if lead_id:
        links = await get_by_lead(lead_id)
    elif conv_uuid:
        links = await get_by_conversation(conv_uuid)

    for ln in links or []:
        try:
            if ln.bot_kind == "master" and tg_master:
                await tg_master.send_message(chat_id=ln.user_id, text=f"{text}")
            if ln.bot_kind == "operator" and tg_operator:
                await tg_operator.send_message(chat_id=ln.user_id, text=f"{text}")
        except Exception:
            logger.exception("TG send failed")

    return {"ok": True}