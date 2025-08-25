"""Handlers for AmoChats webhooks and related helpers."""

import hashlib
import hmac
import logging
import secrets
import base64
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.adapters.amochats import connect_channel
from app.core.config import get_settings
from app.core.guards import require_admin
from app.http_client import get_http_client
from app.services.dedup import calc_key, check_and_store
from app.services.queue import RabbitMQClient, rabbitmq
from app.store_chat import (
    get_by_conversation,
    get_by_lead,
    get_by_user,
    set_conversation,
)

logger = logging.getLogger(__name__)
router_amo_chats = APIRouter()


def _md5_hex(b: bytes) -> str:
    return hashlib.md5(b).hexdigest().lower()


async def verify_amochats_signature(request: Request) -> None:
    raw = await request.body()

    # 1) секрет: если задан отдельный для входящих — используем его, иначе секрет канала
    s = get_settings()
    secret = (getattr(s, "AMOCHATS_INCOMING_SECRET", "") or getattr(s, "AMO_CHATS_SECRET", "")).strip()
    if not secret:
        raise HTTPException(status_code=401, detail="Missing secret")

    got = (request.headers.get("X-Signature") or "").strip().lower()
    if not got:
        raise HTTPException(status_code=401, detail="Missing signature")

    # --- Вариант A: HMAC-SHA1(raw body)
    hmac_body = hmac.new(secret.encode("utf-8"), raw, hashlib.sha1).hexdigest().lower()
    if secrets.compare_digest(got, hmac_body):
        return

    # --- Вариант B: "каноническая строка"
    method = request.method.upper()
    date_hdr = request.headers.get("Date", "")

    raw_ctype = (request.headers.get("Content-Type") or "application/json").strip()
    ct_base = raw_ctype.split(";", 1)[0].strip()
    ctype_variants = []
    for ct in (raw_ctype, ct_base, "application/json"):
        if ct and ct not in ctype_variants:
            ctype_variants.append(ct)

    md5_body = _md5_hex(raw)

    seen_path = request.url.path
    xpref = (request.headers.get("X-Forwarded-Prefix") or "").rstrip("/")
    xorig = request.headers.get("X-Original-URI")
    path_variants = []
    for p in (
            seen_path,
            seen_path.rstrip("/") or "/",
            f"{xpref}{seen_path}" if xpref else None,
            (f"{xpref}{seen_path}".rstrip("/") if xpref else None),
            xorig,
            (xorig.rstrip("/") if xorig else None),
    ):
        if p and p not in path_variants:
            path_variants.append(p)

    def sign(path: str, ctype: str) -> str:
        s2s = "\n".join([method, md5_body, ctype, date_hdr, path])
        return hmac.new(secret.encode("utf-8"), s2s.encode("utf-8"), hashlib.sha1).hexdigest().lower()

    for ct in ctype_variants:
        for p in path_variants:
            if secrets.compare_digest(got, sign(p, ct)):
                return

    # --- не сошлось: лог подробностей
    logger.warning(
        "amo-chats sig-mismatch: got=%s date=%s method=%s md5=%s sha1=%s len=%d "
        "path_seen=%s ctype=%s head64=%s tail64=%s",
        got[:40],
        date_hdr,
        method,
        md5_body,
        hashlib.sha1(raw).hexdigest(),
        len(raw),
        seen_path,
        raw_ctype,
        base64.b64encode(raw[:64]).decode("ascii"),
        base64.b64encode(raw[-64:] if len(raw) >= 64 else raw).decode("ascii"),
    )
    raise HTTPException(status_code=401, detail="Invalid signature")


def parse_lead_id(client_id: str) -> int | None:
    """Extract numeric lead id from a ``lead:<id>`` formatted string."""
    if isinstance(client_id, str) and client_id.startswith("lead:"):
        try:
            return int(client_id.split(":", 1)[1])
        except ValueError:
            return None
    return None


async def parse_json(
        request: Request, raw: bytes, scope_id: str | None
) -> dict | None:
    """Return the JSON body, logging an error if decoding fails."""
    try:
        return await request.json()
    except ValueError:
        txt = raw[:500].decode("utf-8", "ignore")
        logger.warning("amo-chats bad json (scope_id=%s); body=%r", scope_id, txt)
        return None


def extract_message(data: dict) -> tuple[str, str | None, str, dict, dict, str]:
    """Pull message information from the webhook payload."""
    root = data.get("message") or data.get("payload") or {}
    msg = root.get("message") or {}
    text = (msg.get("text") or "").strip()
    conv = root.get("conversation") or {}
    conv_ref_id = conv.get("id") or conv.get("uuid")
    client_id = conv.get("client_id") or ""
    sender = root.get("sender") or {}
    receiver = root.get("receiver") or {}
    msg_id = (
            root.get("msgid")
            or msg.get("id")
            or msg.get("uuid")
            or msg.get("message_id")
            or ""
    )
    return text, conv_ref_id, client_id, sender, receiver, msg_id


async def set_conv_for_links(links, conv_ref_id: str) -> None:
    """Update links with the provided conversation reference."""
    for ln in links:
        if not ln.conversation_id:
            await set_conversation(ln.user_id, ln.bot_kind, conv_ref_id)


def parse_tg_uid(ext_id: str) -> int | None:
    """Extract Telegram user id from an external ``tg:<id>`` identifier."""
    if isinstance(ext_id, str) and ext_id.startswith("tg:"):
        try:
            return int(ext_id.split(":", 1)[1])
        except ValueError:
            logger.warning("amo-chats failed to parse tg uid from ext_id %r", ext_id)
    return None


async def links_from_ext_id(
        conv_ref_id: str | None, sender: dict, receiver: dict
):
    """Return chat links using an external identifier such as Telegram UID."""
    ext_id = (
            sender.get("client_id")
            or sender.get("id")
            or receiver.get("client_id")
            or receiver.get("id")
            or ""
    )
    tg_uid = parse_tg_uid(ext_id)
    if not tg_uid:
        return []
    cand = []
    ln1 = await get_by_user(tg_uid, "master")
    if ln1:
        cand.append(ln1)
    ln2 = await get_by_user(tg_uid, "operator")
    if ln2:
        cand.append(ln2)
    links = [ln for ln in cand if not ln.conversation_id] or cand
    if links and conv_ref_id:
        await set_conv_for_links(links, conv_ref_id)
    return links


async def resolve_links(
        conv_ref_id: str | None, lead_id: int | None, sender: dict, receiver: dict
):
    """Resolve links based on conversation, lead, or external identifiers."""
    links = []
    if conv_ref_id:
        links = await get_by_conversation(conv_ref_id)
    if not links and lead_id:
        links = await get_by_lead(lead_id)
        if links and conv_ref_id:
            await set_conv_for_links(links, conv_ref_id)
    if not links:
        links = await links_from_ext_id(conv_ref_id, sender, receiver)
    return links


async def publish_links(
        queue_client: RabbitMQClient,
        links,
        conv_ref_id: str | None,
        msg_id: str,
        text: str,
) -> None:
    """Publish mirrored messages to the queue for each link."""
    for ln in links or []:
        key_src = (
            f"amo:{conv_ref_id}:{msg_id or hashlib.sha256((text or '').encode()).hexdigest()[:16]}"
        )
        await queue_client.publish_task(
            {
                "platform": "mirror",
                "action": "amo_to_tg",
                "bot_kind": ln.bot_kind,
                "user_id": ln.user_id,
                "text": text,
                "msg_key": key_src,
            }
        )


async def is_duplicate(raw: bytes) -> bool:
    """Check if the incoming payload has been processed before."""
    key = calc_key("amo_chats", raw)
    return not await check_and_store(key)


@router_amo_chats.post(
    "/webhooks/amo-chats/in/{scope_id}",
    dependencies=[Depends(verify_amochats_signature)],
)
async def amochats_in(
        request: Request,
        scope_id: str,
        queue_client: RabbitMQClient = Depends(lambda: rabbitmq),
):
    """Process incoming AmoChats webhook and mirror messages to Telegram."""
    raw = await request.body()

    if await is_duplicate(raw):
        logger.info("amo-chats duplicate webhook skipped (scope_id=%s)", scope_id)
        return {"ok": True, "duplicate": True}

    data = await parse_json(request, raw, scope_id)
    if data is None:
        return {"ok": False, "error": "bad json"}

    text, conv_ref_id, client_id, sender, receiver, msg_id = extract_message(data)
    if not text:
        return {"ok": True}

    logger.info(
        "amo-chats IN: scope=%s conv_id=%s client_id=%s text_len=%d",
        scope_id,
        conv_ref_id,
        client_id,
        len(text),
    )

    lead_id = parse_lead_id(client_id)
    links = await resolve_links(conv_ref_id, lead_id, sender, receiver)

    logger.info(
        "amo-chats links found: %d (conv=%s lead=%s)",
        len(links),
        conv_ref_id,
        lead_id,
    )

    await publish_links(queue_client, links, conv_ref_id, msg_id, text)

    logger.info(
        "amo-chats -> RMQ mirror ok (scope_id=%s, text_len=%d)",
        scope_id,
        len(text),
    )
    return {"ok": True}


# --- Админ для одноразового /connect ---
amo_admin = APIRouter(
    prefix="/admin/amo-chats", dependencies=[Depends(require_admin)]
)


@amo_admin.post("/connect")
async def admin_connect(http_client: httpx.AsyncClient = Depends(get_http_client)):
    """Initiate a one-time connection to AmoChats from the admin panel."""
    resp = await connect_channel(http_client)
    return {"ok": True, "response": resp}
