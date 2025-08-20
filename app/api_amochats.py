import logging, hmac, hashlib, secrets
from fastapi import APIRouter, Request, Response, Depends

from app.amochats import connect_channel
from app.dedup import calc_key, check_and_store
from app.guards import require_admin
from app.store_chat import get_by_lead, get_by_conversation, set_conversation, get_by_user
from app.config import settings
from app.queue import publish_task

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
    sender = root.get("sender") or {}
    receiver = root.get("receiver") or {}

    # попытаемся вытащить msgid для идемпотентности
    msg_id = (root.get("msgid")
              or msg.get("id")
              or msg.get("uuid")
              or msg.get("message_id")
              or "")

    logger.info("amo-chats IN: scope=%s conv_id=%s client_id=%s text_len=%d",
                scope_id, conv_ref_id, client_id, len(text))

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

    if not links:
        ext_id = (sender.get("client_id") or sender.get("id") or
                  receiver.get("client_id") or receiver.get("id") or "")
        tg_uid = None
        if isinstance(ext_id, str) and ext_id.startswith("tg:"):
            try:
                tg_uid = int(ext_id.split(":", 1)[1])
            except:
                pass

        if tg_uid:
            cand = []
            ln1 = await get_by_user(tg_uid, "master")
            if ln1: cand.append(ln1)
            ln2 = await get_by_user(tg_uid, "operator")
            if ln2: cand.append(ln2)
            links = [ln for ln in cand if not ln.conversation_id] or cand
            if links and conv_ref_id:
                for ln in links:
                    if not ln.conversation_id:
                        await set_conversation(ln.user_id, ln.bot_kind, conv_ref_id)

    logger.info("amo-chats links found: %d (conv=%s lead=%s)", len(links), conv_ref_id, lead_id)

    # вместо мгновенной отправки в TG — публикуем в очередь
    for ln in links or []:
        bot_kind = ln.bot_kind
        user_id = ln.user_id
        # надёжный ключ против дублей
        key_src = f"amo:{conv_ref_id}:{msg_id or hashlib.sha1((text or '').encode()).hexdigest()[:16]}"
        await publish_task({
            "platform": "mirror",
            "action": "amo_to_tg",
            "bot_kind": bot_kind,
            "user_id": user_id,
            "text": text,
            "msg_key": key_src,
        })

    logger.info("amo-chats -> RMQ mirror ok (scope_id=%s, text_len=%d)", scope_id, len(text))
    return {"ok": True}

# --- Админ для одноразового /connect ---
from fastapi import APIRouter as _APIRouter  # avoid shadow
amo_admin = _APIRouter(prefix="/admin/amo-chats", dependencies=[Depends(require_admin)])

@amo_admin.post("/connect")
async def admin_connect():
    resp = await connect_channel()
    return {"ok": True, "response": resp}
