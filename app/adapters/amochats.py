"""Utilities for interacting with the AmoChats API."""

import hashlib
import hmac
import json
import logging
import time
import uuid
from email.utils import formatdate
from functools import lru_cache

import httpx

from app.core.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


class AmoChatsError(Exception):
    """Generic error raised for AmoChats integration issues."""


class AmoChatsClient:  # pylint: disable=too-few-public-methods
    """Helper validating required AmoChats settings once."""

    def __init__(self):
        req = {
            "AMO_CHATS_SCOPE_ID": getattr(settings, "AMO_CHATS_SCOPE_ID", None),
            "AMO_CHATS_SECRET": getattr(settings, "AMO_CHATS_SECRET", None),
            "AMO_CHATS_ACCOUNT_ID": getattr(settings, "AMO_CHATS_ACCOUNT_ID", None),
            "AMO_CHATS_CHANNEL_ID": getattr(settings, "AMO_CHATS_CHANNEL_ID", None),
            "AMO_CHATS_SENDER_USER_AMOJO_ID": getattr(
                settings, "AMO_CHATS_SENDER_USER_AMOJO_ID", None
            ),
        }
        missing = [k for k, v in req.items() if not v]
        if missing:
            joined = "/".join(missing)
            raise AmoChatsError(f"AmoChats env not configured ({joined})")
        self.scope_id = req["AMO_CHATS_SCOPE_ID"]
        self.secret = req["AMO_CHATS_SECRET"]
        self.account_id = req["AMO_CHATS_ACCOUNT_ID"]
        self.channel_id = req["AMO_CHATS_CHANNEL_ID"]
        self.sender_user_amojo_id = req["AMO_CHATS_SENDER_USER_AMOJO_ID"]


@lru_cache(maxsize=1)
def _get_client() -> AmoChatsClient:
    """Return a cached :class:`AmoChatsClient` instance."""
    return AmoChatsClient()


def _base() -> str:
    return "https://amojo.amocrm.ru"


def _dump(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _build_headers(
    secret: str,
    method: str,
    path: str,
    body: bytes,
    account_id: str | None,
) -> dict:
    """Construct request headers for AmoChats API call."""
    date = formatdate(usegmt=True)
    ctype = "application/json"
    md5 = hashlib.md5(body).hexdigest().lower()
    to_sign = "\n".join([method.upper(), md5, ctype, date, path])
    sig = hmac.new(  # nosec B324
        secret.encode("utf-8"), to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest().lower()
    headers = {
        "Date": date,
        "Content-Type": ctype,
        "Content-MD5": md5,
        "X-Signature": sig,
    }
    if account_id:
        headers["X-Client-Id"] = account_id
    return headers


async def connect_channel(client: httpx.AsyncClient) -> dict:
    """Connect AmoChats channel once, safe to call multiple times."""
    ac = _get_client()

    path = f"/v2/origin/custom/{ac.channel_id}/connect"
    url = f"https://amojo.amocrm.ru{path}"
    body = _dump({
        "account_id": ac.account_id,
        "hook_api_version": "v2",
        "title": getattr(settings, "AMOCHATS_INTEGRATION_NAME", "tg-bridge"),
    })
    headers = _build_headers(ac.secret, "POST", path, body, ac.account_id)
    r = await client.post(url, content=body, headers=headers, timeout=30)
    if r.status_code >= 400:
        raise AmoChatsError(f"connect failed {r.status_code}: {r.text}")
    return r.json() if r.content else {}


async def ensure_amo_chats_connected(log, client: httpx.AsyncClient) -> None:
    """Ensure AmoChats channel is connected when autoconnect is enabled."""
    if not getattr(settings, "AMO_CHATS_AUTOCONNECT", False):
        log.info("AmoChats autoconnect disabled")
        return
    try:
        await connect_channel(client)
        log.info("AmoChats channel connected (v2)")
    except AmoChatsError as exc:
        # если уже подключён — Amo обычно вернёт 200/204; на всякий логируем warning
        log.warning("AmoChats connect warning: %s", exc)


async def send_text_from_client(  # pylint: disable=too-many-arguments,too-many-locals
    *,
    lead_id: int,
    text: str,
    tg_user_id: int,
    tg_user_name: str | None = None,
    conversation_id: str | None = None,
    client: httpx.AsyncClient,
) -> str | None:
    """Send message from a client to AmoChats and return conversation id."""
    ac = _get_client()

    path = f"/v2/origin/custom/{ac.scope_id}"
    url = _base() + path

    now_s = int(time.time())
    now_ms = int(time.time() * 1000)

    def _payload(with_ref: bool):
        base = {
            "event_type": "new_message",
            "payload": {
                "msgid": str(uuid.uuid4()),
                "timestamp": now_s,
                "msec_timestamp": now_ms,
                "sender": {
                    "id": f"tg:{tg_user_id}",
                    "name": tg_user_name or f"tg_{tg_user_id}",
                },
                "message": {"type": "text", "text": text},
            },
        }
        if with_ref:
            base["payload"]["conversation_ref_id"] = f"lead:{lead_id}"
        else:
            base["payload"]["conversation_id"] = conversation_id
        return base

    async def _post(payload: dict, route: str):
        body = _dump(payload)
        headers = _build_headers(ac.secret, "POST", path, body, ac.account_id)
        logger.debug("send_from_client POST %s -> %s bytes", route, len(body))
        response = await client.post(url, content=body, headers=headers, timeout=30)
        logger.debug(
            "send_from_client %s response %s %s",
            route,
            response.status_code,
            response.text[:200],
        )
        return response

    # Если conv_id неизвестен — сразу по ref_id
    if not conversation_id:
        logger.info("send_from_client: lead=%s conv=- route=ref", lead_id)
        r = await _post(_payload(with_ref=True), "ref")
        if r.status_code >= 400:
            logger.error(
                "send_from_client(ref) failed lead=%s status=%s body=%s",
                lead_id,
                r.status_code,
                r.text,
            )
            raise AmoChatsError(
                f"send_text_from_client failed (ref) {r.status_code}: {r.text}"
            )
    else:
        logger.info(
            "send_from_client: lead=%s conv=%s route=id", lead_id, conversation_id
        )
        r = await _post(_payload(with_ref=False), "id")
        if r.status_code >= 400:
            logger.warning(
                "send_from_client(id) failed -> retry by ref_id: lead=%s status=%s",
                lead_id,
                r.status_code,
            )
            r2 = await _post(_payload(with_ref=True), "ref")
            if r2.status_code >= 400:
                logger.error(
                    "send_from_client retry(ref) failed lead=%s id->%s:%s ref->%s:%s",
                    lead_id,
                    r.status_code,
                    r.text,
                    r2.status_code,
                    r2.text,
                )
                raise AmoChatsError(
                    f"send_text_from_client failed. id-> {r.status_code}:{r.text} ; "
                    f"ref-> {r2.status_code}:{r2.text}"
                )
            r = r2

    data = r.json() if r.content else {}
    conv = (data.get("conversation") or {})
    cid = conv.get("uuid") or conv.get("id")
    logger.info("send_from_client: ok conv_id=%s text_len=%d", cid, len(text))
    return cid


async def send_text_from_manager(  # pylint: disable=too-many-arguments
    *,
    conversation_id: str,  # здесь нужен уже существующий uuid/id чата
    user_id: int,
    user_name: str | None,
    avatar: str | None,
    text: str,
    client: httpx.AsyncClient,
) -> None:
    """
    Сообщение 'от менеджера' — используем sender.ref_id = AMO_CHATS_SENDER_USER_AMOJO_ID,
    а в receiver кладём данные клиента (опционально).
    """
    ac = _get_client()

    path = f"/v2/origin/custom/{ac.scope_id}"
    url = _base() + path

    now_s = int(time.time())
    now_ms = int(time.time() * 1000)

    payload = {
        "event_type": "new_message",
        "payload": {
            "msgid": str(uuid.uuid4()),
            "timestamp": now_s,
            "msec_timestamp": now_ms,
            "conversation_id": conversation_id,
            "sender": {"ref_id": ac.sender_user_amojo_id},
            "receiver": {
                "id": str(user_id),
                **({"name": user_name} if user_name else {}),
                **({"avatar": avatar} if avatar else {}),
            },
            "message": {"type": "text", "text": text},
        },
    }

    body = _dump(payload)
    headers = _build_headers(ac.secret, "POST", path, body, ac.account_id)

    r = await client.post(url, content=body, headers=headers, timeout=30)
    if r.status_code >= 400:
        raise AmoChatsError(f"send_text_from_manager failed {r.status_code}: {r.text}")


async def ensure_chat_created(  # pylint: disable=too-many-locals
    *,
    lead_id: int,
    tg_user_id: int,
    tg_user_name: str | None,
    client: httpx.AsyncClient,
) -> str:
    """
    Форсирует создание/поиск чата в AmoChats по conversation_ref_id='lead:<id>'.
    Возвращает conversation_id (uuid). Сообщение-системка видно только в чате Amo.
    """
    ac = _get_client()

    path = f"/v2/origin/custom/{ac.scope_id}"
    url = _base() + path

    now_s = int(time.time())
    now_ms = int(time.time() * 1000)

    payload = {
        "event_type": "new_message",
        "payload": {
            "msgid": str(uuid.uuid4()),
            "timestamp": now_s,
            "msec_timestamp": now_ms,
            "conversation_ref_id": f"lead:{lead_id}",
            "sender": {
                "id": f"tg:{tg_user_id}",
                "name": (tg_user_name or f"tg_{tg_user_id}"),
            },
            "message": {"type": "text", "text": "🔗 Пользователь открыл бота (инициализация чата)"},
        },
    }
    body = _dump(payload)
    headers = _build_headers(ac.secret, "POST", path, body, ac.account_id)
    r = await client.post(url, content=body, headers=headers, timeout=30)
    if r.status_code >= 400:
        raise AmoChatsError(f"ensure_chat_created failed {r.status_code}: {r.text}")

    logger.info("ensure_chat_created: lead=%s tg=%s (%s)", lead_id, tg_user_id, tg_user_name or "-")

    data = r.json() if r.content else {}
    conv = (data.get("conversation") or {})
    cid = conv.get("uuid") or conv.get("id")
    if not cid:
        raise AmoChatsError("ensure_chat_created: no conversation id in response")
    logger.info("ensure_chat_created: got conversation_id=%s for lead=%s", cid, lead_id)
    return cid
