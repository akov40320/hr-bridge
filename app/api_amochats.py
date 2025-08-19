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

    if settings.AMOCHATS_INCOMING_SECRET:
        got = request.headers.get("X-Signature", "")
        calc = hmac.new(settings.AMOCHATS_INCOMING_SECRET.encode(), raw, hashlib.sha1).hexdigest()
        if got.lower() != calc.lower():
            logger.warning("amo-chats invalid signature")
            return Response(status_code=401)

    key = calc_key("amo_chats", raw)
    if not await check_and_store(key):
        logger.info("amo-chats duplicate webhook skipped")
        return {"ok": True, "duplicate": True}

    # --- пробуем распарсить в любом случае и логируем фрагмент, если не вышло ---
    try:
        data = await request.json()
    except Exception:
        txt = raw[:500].decode("utf-8", "ignore")
        logger.warning("amo-chats bad json; headers=%s; body=%r", dict(request.headers), txt)
        return {"ok": False, "error": "bad json"}

    # v2 присылает { "message": {...} } (иногда { "payload": {...} })
    root = data.get("message") or data.get("payload") or {}
    msg = root.get("message") or {}
    text = (msg.get("text") or "").strip()
    if not text:
        return {"ok": True}

    conv = root.get("conversation") or {}
    conv_ref_id = conv.get("id") or conv.get("uuid")
    client_id = conv.get("client_id") or ""

    lead_id = None
    if isinstance(client_id, str) and client_id.startswith("lead:"):
        try:
            lead_id = int(client_id.split(":", 1)[1])
        except Exception:
            pass

    links = []
    if conv_ref_id:
        links = await get_by_conversation(conv_ref_id)
    if not links and lead_id:
        links = await get_by_lead(lead_id)
        if links and conv_ref_id:
            for ln in links:
                if not ln.conversation_id:
                    await set_conversation(ln.user_id, ln.bot_kind, conv_ref_id)

    for ln in links or []:
        try:
            token = settings.TELEGRAM_MASTER_BOT_TOKEN if ln.bot_kind == "master" else settings.TELEGRAM_OPERATOR_BOT_TOKEN
            if token:
                async with Bot(token) as bot:
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
