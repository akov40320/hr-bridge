import logging, hmac, hashlib
from fastapi import APIRouter, Request, Response, Depends
from aiogram import Bot
from app.amochats import connect_channel
from app.dedup import calc_key, check_and_store
from app.guards import require_admin
from app.store_chat import get_by_lead, get_by_conversation, set_conversation
from app.config import settings

logger = logging.getLogger(__name__)
router_amo_chats = APIRouter()


def _valid_hook_signature(secret: str, raw_body: bytes, got_sig: str) -> bool:
    if not secret: return True
    if not got_sig: return False
    calc = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha1).hexdigest()
    return got_sig.lower() == calc.lower()


@router_amo_chats.post("/webhooks/amo-chats/in")
async def amochats_in(request: Request):
    raw = await request.body()

    # Подпись HMAC тела (секрет = секрет канала)
    if settings.AMOCHATS_INCOMING_SECRET:
        got = request.headers.get("X-Signature", "")
        if not _valid_hook_signature(settings.AMOCHATS_INCOMING_SECRET, raw, got):
            return Response(status_code=401)

    # Дедуп по хэшу тела
    key = calc_key("amo_chats", raw)
    if not await check_and_store(key):
        logger.info("amo-chats duplicate webhook skipped")
        return {"ok": True, "duplicate": True}

    # Разбор v2
    try:
        data = await request.json()
    except Exception:
        logger.warning("amo-chats bad json")
        return {"ok": False, "error": "bad json"}

    if (data.get("event_type") or "").lower() != "new_message":
        return {"ok": True}  # игнорим не-сообщения

    msg_root = data.get("message") or {}
    msg_obj = msg_root.get("message") or {}
    text = (msg_obj.get("text") or "").strip()
    if not text:
        return {"ok": True}

    conv = msg_root.get("conversation") or {}
    conv_ref_id = conv.get("id") or conv.get("uuid")  # v2=id, на всякий берём uuid
    client_id = conv.get("client_id") or ""

    lead_id = None
    if isinstance(client_id, str) and client_id.startswith("lead:"):
        try:
            lead_id = int(client_id.split(":", 1)[1])
        except Exception:
            lead_id = None

    links = []
    if lead_id:
        links = await get_by_lead(lead_id)
    elif conv_ref_id:
        links = await get_by_conversation(conv_ref_id)

    # Если получили реальный conv_id от amo, а в линке он пуст — сохраним
    if conv_ref_id and links:
        for ln in links:
            if not ln.conversation_id:
                try:
                    await set_conversation(ln.user_id, ln.bot_kind, conv_ref_id)
                except Exception:
                    logger.exception("set_conversation failed")

    # Отправка в TG — создаём бота по месту, чтобы не течь сессиями
    for ln in links or []:
        try:
            if ln.bot_kind == "master" and settings.TELEGRAM_MASTER_BOT_TOKEN:
                async with Bot(settings.TELEGRAM_MASTER_BOT_TOKEN) as bot:
                    await bot.send_message(chat_id=ln.user_id, text=text)
            if ln.bot_kind == "operator" and settings.TELEGRAM_OPERATOR_BOT_TOKEN:
                async with Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN) as bot:
                    await bot.send_message(chat_id=ln.user_id, text=text)
        except Exception:
            logger.exception("TG send failed")

    return {"ok": True}


# --- Админ для одноразового /connect ---
amo_admin = APIRouter(prefix="/admin/amo-chats", dependencies=[Depends(require_admin)])


@amo_admin.post("/connect")
async def admin_connect():
    resp = await connect_channel()
    return {"ok": True, "response": resp}
