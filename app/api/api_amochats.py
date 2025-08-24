"""Handlers for AmoChats webhooks and related helpers."""

import hashlib
import hmac
import logging
import secrets

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


def _calc_sig(secret: str, method: str, path: str, body: bytes, content_type: str, date_hdr: str) -> str:
    string_to_sign = "\n".join([
        method.upper(),
        _md5_hex(body),
        content_type,
        date_hdr,
        path,
    ])
    return hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).hexdigest().lower()


async def verify_amochats_signature(request: Request) -> None:
    raw = await request.body()
    s = get_settings()

    # важное: это должен быть тот же секрет, что используешь при исходящих запросах
    secret = (getattr(s, "AMO_CHATS_SECRET", None)
              or getattr(s, "AMOCHATS_INCOMING_SECRET", "") or "")
    if not secret:
        return  # в крайнем случае пропускаем проверку

    got = (request.headers.get("X-Signature") or "").lower()
    date_hdr = request.headers.get("Date", "")
    raw_ctype = request.headers.get("Content-Type", "application/json")
    method = request.method

    # кандидаты Content-Type
    ctype_candidates = []
    head = raw_ctype.strip()
    base = raw_ctype.split(";", 1)[0].strip()
    for ct in (head, base, "application/json"):
        if ct and ct not in ctype_candidates:
            ctype_candidates.append(ct)

    # кандидаты PATH (на случай префиксов/переписей)
    path_candidates = []
    seen = request.url.path
    xpref = request.headers.get("X-Forwarded-Prefix")
    xorig = request.headers.get("X-Original-URI")
    for p in (
        seen,
        (seen.rstrip("/") or "/"),
        (f"{(xpref or '').rstrip('/')}{seen}" if xpref else None),
        xorig,
        (xorig.rstrip("/") if xorig else None),
    ):
        if p and p not in path_candidates:
            path_candidates.append(p)

    ok = False
    for ct in ctype_candidates:
        for p in path_candidates:
            calc = _calc_sig(secret, method, p, raw, ct, date_hdr)
            if secrets.compare_digest(calc, got):
                ok = True
                break
        if ok:
            break

    if not ok:
        logger.warning(
            "amo-chats invalid signature: got=%s ctype=%s path=%s sha256(body)=%s len=%d",
            got[:12], raw_ctype, seen, hashlib.sha256(raw).hexdigest()[:12], len(raw)
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
    scope_id: str | None = None,
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
