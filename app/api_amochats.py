import logging, hmac, hashlib
from fastapi import APIRouter, Request, Response
from aiogram import Bot

from app.dedup import calc_key, check_and_store
from app.store_chat import get_by_lead, get_by_conversation
from app.config import settings

logger = logging.getLogger(__name__)
router_amo_chats = APIRouter()

tg_master = Bot(settings.TELEGRAM_MASTER_BOT_TOKEN) if settings.TELEGRAM_MASTER_BOT_TOKEN else None
tg_operator = Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN) if settings.TELEGRAM_OPERATOR_BOT_TOKEN else None


def _valid_hook_signature(secret: str, raw_body: bytes, got_sig: str) -> bool:
    if not secret:
        return True  # выключена проверка
    if not got_sig:
        return False
    calc = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha1).hexdigest()
    return got_sig.lower() == calc.lower()


@router_amo_chats.post("/webhooks/amo-chats/in")
async def amochats_in(request: Request):
    raw = await request.body()

    # Проверка HMAC подписи входящего хука (v2): X-Signature = HMAC-SHA1(body, channel_secret)
    if settings.AMOCHATS_INCOMING_SECRET:
        got = request.headers.get("X-Signature", "")
        if not _valid_hook_signature(settings.AMOCHATS_INCOMING_SECRET, raw, got):
            return Response(status_code=401)

    # Дедупликатор
    key = calc_key("amo_chats", raw)
    if not await check_and_store(key):
        logger.info("amo-chats duplicate webhook skipped")
        return {"ok": True, "duplicate": True}

    # Тело хука v2
    try:
        data = await request.json()
    except Exception:
        logger.warning("amo-chats bad json")
        return {"ok": False, "error": "bad json"}

    # v2: все в корне -> message{ conversation{}, message{} ... }
    msg_root = data.get("message") or {}
    msg_obj = msg_root.get("message") or {}
    text = (msg_obj.get("text") or "").strip()

    # можно игнорить не-текст; оставь при желании передачу файлов/медиа
    if not text:
        return {"ok": True}

    conv = msg_root.get("conversation") or {}
    # ID чата в API Чатов (amojo)
    conv_ref_id = conv.get("id") or conv.get("uuid")  # v2 = id; fallback на старый uuid
    # ID чата на стороне интеграции (твой conversation_id); при "Написать первым" может отсутствовать
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
        # храни маппинг amojo-conversation-id -> твои TG-связки
        links = await get_by_conversation(conv_ref_id)

    for ln in links or []:
        try:
            if ln.bot_kind == "master" and tg_master:
                await tg_master.send_message(chat_id=ln.user_id, text=text)
            if ln.bot_kind == "operator" and tg_operator:
                await tg_operator.send_message(chat_id=ln.user_id, text=text)
        except Exception:
            logger.exception("TG send failed")

    return {"ok": True}
