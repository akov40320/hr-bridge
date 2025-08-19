import logging, hmac, hashlib, secrets
from fastapi import APIRouter, Request, Response, Depends
from aiogram import Bot
from app.amochats import connect_channel
from app.dedup import calc_key, check_and_store
from app.guards import require_admin
from app.store_chat import get_by_lead, get_by_conversation, set_conversation
from app.config import settings

logger = logging.getLogger(__name__)
router_amo_chats = APIRouter()


def _hmac_body(secret: str, raw: bytes) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha1).hexdigest().lower()

@router_amo_chats.post("/webhooks/amo-chats/in/{scope_id}")
async def amochats_in(request: Request, scope_id: str | None = None):
    raw = await request.body()
    if settings.AMOCHATS_INCOMING_SECRET:
        got = (request.headers.get("X-Signature") or "").lower()
        calc = _hmac_body(settings.AMOCHATS_INCOMING_SECRET, raw)
        if not (got and secrets.compare_digest(got, calc)):
            logger.warning(
                "amo-chats invalid signature: got=%s calc=%s sha1(body)=%s len=%d path=%s",
                got[:12], calc[:12], hashlib.sha1(raw).hexdigest()[:12], len(raw), request.url.path
            )
            return Response(status_code=401)

    key = calc_key("amo_chats", raw)
    if not await check_and_store(key):
        logger.info("amo-chats duplicate webhook skipped (scope_id=%s)", scope_id)
        return {"ok": True, "duplicate": True}

    try:
        data = await request.json()
    except Exception:
        txt = raw[:500].decode("utf-8", "ignore")
        logger.warning("amo-chats bad json (scope_id=%s); body=%r", scope_id, txt)
        return {"ok": False, "error": "bad json"}

    # v2 формат
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
            token = (settings.TELEGRAM_MASTER_BOT_TOKEN if ln.bot_kind == "master"
                     else settings.TELEGRAM_OPERATOR_BOT_TOKEN)
            if token:
                async with Bot(token) as bot:
                    await bot.send_message(chat_id=ln.user_id, text=text)
        except Exception:
            logger.exception("TG send failed (scope_id=%s)", scope_id)

    logger.info("amo-chats -> TG ok (scope_id=%s, text_len=%d)", scope_id, len(text))
    return {"ok": True}


# --- Админ для одноразового /connect ---
amo_admin = APIRouter(prefix="/admin/amo-chats", dependencies=[Depends(require_admin)])


@amo_admin.post("/connect")
async def admin_connect():
    resp = await connect_channel()
    return {"ok": True, "response": resp}
