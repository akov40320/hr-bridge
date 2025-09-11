"""Utilities for interacting with the AmoChats API."""

from typing import Any, cast
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

    def __init__(self) -> None:
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
        self.scope_id: str = cast(str, req["AMO_CHATS_SCOPE_ID"])
        self.secret: str = cast(str, req["AMO_CHATS_SECRET"])
        self.account_id: str = cast(str, req["AMO_CHATS_ACCOUNT_ID"])
        self.channel_id: str = cast(str, req["AMO_CHATS_CHANNEL_ID"])
        self.sender_user_amojo_id: str = cast(str, req["AMO_CHATS_SENDER_USER_AMOJO_ID"])


@lru_cache(maxsize=1)
def _get_client() -> AmoChatsClient:
    """Return a cached :class:`AmoChatsClient` instance."""
    return AmoChatsClient()


def _base() -> str:
    return "https://amojo.amocrm.ru"


def _dump(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _build_headers(
        secret: str,
        method: str,
        path: str,
        body: bytes | None,
        account_id: str | None = None,  # <— добавили
) -> dict[str, str]:
    date_hdr = formatdate(usegmt=True)
    ctype = "application/json"
    b = body or b""
    md5_hex = hashlib.md5(b).hexdigest().lower()
    string_to_sign = "\n".join([method.upper(), md5_hex, ctype, date_hdr, path])
    sig = hmac.new(secret.encode("utf-8"),
                   string_to_sign.encode("utf-8"),
                   hashlib.sha1).hexdigest().lower()

    headers = {
        "Date": date_hdr,
        "Content-Type": ctype,
        "Content-MD5": md5_hex,
        "X-Signature": sig,
    }
    # если нужно — прокидывай айди аккаунта
    if account_id:
        headers["X-Account-Id"] = account_id

    return headers


async def connect_channel(client: httpx.AsyncClient) -> dict[str, Any]:
    """Connect AmoChats channel once, safe to call multiple times."""
    ac = _get_client()

    path = f"/v2/origin/custom/{ac.channel_id}/connect"
    url = f"{_base()}{path}"
    body = _dump(
        {
            "account_id": ac.account_id,
            "hook_api_version": "v2",
            "title": getattr(settings, "AMOCHATS_INTEGRATION_NAME", "tg-bridge"),
        }
    )
    headers = _build_headers(ac.secret, "POST", path, body)
    r = await client.post(url, content=body, headers=headers, timeout=30)
    if r.status_code >= 400:
        raise AmoChatsError(f"connect failed {r.status_code}: {r.text}")
    return r.json() if r.content else {}


async def ensure_amo_chats_connected(log: logging.Logger, client: httpx.AsyncClient) -> None:
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


async def send_text_from_client(
        *, lead_id: int, text: str, tg_user_id: int, tg_user_name: str | None = None,
        conversation_id: str | None = None, client: httpx.AsyncClient,
) -> str | None:
    ac = _get_client()

    if not conversation_id:
        conversation_id = await ensure_chat_created(
            lead_id=lead_id, tg_user_id=tg_user_id, tg_user_name=tg_user_name, client=client
        )

    path = f"/v2/origin/custom/{ac.scope_id}"
    url = _base() + path

    now_s = int(time.time());
    now_ms = int(time.time() * 1000)
    payload = {
        "event_type": "new_message",
        "payload": {
            "msgid": str(uuid.uuid4()),
            "timestamp": now_s,
            "msec_timestamp": now_ms,
            "conversation_id": conversation_id,  # <-- интеграционный ID
            "sender": {"id": f"tg:{tg_user_id}", "name": tg_user_name or f"tg_{tg_user_id}"},
            "message": {"type": "text", "text": text},
        },
    }
    body = _dump(payload)
    headers = _build_headers(ac.secret, "POST", path, body, ac.account_id)
    r = await client.post(url, content=body, headers=headers, timeout=30)
    if r.status_code >= 400:
        raise AmoChatsError(f"send_text_from_client failed {r.status_code}: {r.text}")

    # можно просто вернуть тот же интеграционный conversation_id
    logger.info("send_from_client: ok conv_id=%s text_len=%d", conversation_id, len(text))
    return conversation_id


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

    payload: dict[str, Any] = {
        "event_type": "new_message",
        "payload": {
            "msgid": str(uuid.uuid4()),
            "timestamp": now_s,
            "msec_timestamp": now_ms,
            "conversation_id": conversation_id,
            "sender": {"ref_id": ac.sender_user_amojo_id},
            "receiver": {
                "id": f"tg:{user_id}",
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


async def ensure_chat_created(
        *,
        lead_id: int,
        tg_user_id: int,
        tg_user_name: str | None,
        client: httpx.AsyncClient,
        contact_id: int | None = None,
        bind_contact_id: int | None = None,
        init_text: str | None = None,
        init_as_manager: bool = False,
        send_default_system: bool = False,
) -> str:
    """
    Создаёт (или находит) чат в AmoChats по conversation_id='lead:<lead_id>'.
    При необходимости сразу отправляет первое сообщение.

    Возвращает:
        str: conversation_id (тот же детерминированный 'lead:<lead_id>')
    """

    from app.adapters.amo_client import AmoClient

    ac = _get_client()

    # стабильный ID чата на стороне интеграции
    conv_id = f"contact:{contact_id}" if contact_id else f"lead:{lead_id}"

    # 1) создать/найти чат
    path_chats = f"/v2/origin/custom/{ac.scope_id}/chats"
    url_chats = _base() + path_chats
    body_chats = _dump({
        "conversation_id": conv_id,
        "user": {
            "id": f"tg:{tg_user_id}",
            "name": tg_user_name or f"tg_{tg_user_id}",
        },

    })
    headers_chats = _build_headers(ac.secret, "POST", path_chats, body_chats, ac.account_id)
    r = await client.post(url_chats, content=body_chats, headers=headers_chats, timeout=30)
    if r.status_code >= 400:
        raise AmoChatsError(f"ensure_chat_created failed {r.status_code}: {r.text}")

    logger.info("ensure_chat_created: ok for lead=%s -> conv_id=%s", lead_id, conv_id)

    # попытаться вытащить chat_id из ответа
    chat_id: str | None = None
    try:
        jr = r.json() if r.content else {}
        # разные инсталляции могут отдать по-разному — пробуем распространённые места
        chat_id = (
                jr.get("chat_id")
                or jr.get("id")
                or (jr.get("payload") or {}).get("chat_id")
                or (jr.get("_embedded") or {}).get("chats", [{}])[0].get("id")
        )
    except Exception:  # pragma: no cover
        logger.warning("ensure_chat_created: parse chat_id failed", exc_info=True)

    logger.info("ensure_chat_created: ok for %s -> conv_id=%s chat_id=%s",
                ("contact" if contact_id else "lead"),
                conv_id, chat_id or "-")

    # 1.1) при желании — сразу привяжем чат к контакту
    if bind_contact_id and chat_id:
        try:
            amo = await AmoClient.create(client)
            await amo.bind_chat_to_contact(bind_contact_id, chat_id)
            logger.info("chat bound to contact: contact_id=%s chat_id=%s", bind_contact_id, chat_id)
        except Exception:
            logger.warning("bind chat to contact failed", exc_info=True)

    # 2) опционально отправить первое сообщение
    path_msg = f"/v2/origin/custom/{ac.scope_id}"
    url_msg = _base() + path_msg
    def _now():
        return int(time.time()), int(time.time() * 1000)

    try:
        if init_text:
            ts, ts_ms = _now()
            sender_block: dict[str, Any]
            if init_as_manager:
                # как менеджер
                sender_block = {"ref_id": ac.sender_user_amojo_id}
            else:
                # как кандидат
                sender_block = {"id": f"tg:{tg_user_id}", "name": tg_user_name or f"tg_{tg_user_id}"}

            init_payload: dict[str, Any] = {
                "event_type": "new_message",
                "payload": {
                    "msgid": str(uuid.uuid4()),
                    "timestamp": ts,
                    "msec_timestamp": ts_ms,
                    "conversation_id": conv_id,
                    "sender": sender_block,
                    "message": {"type": "text", "text": init_text},
                },
            }
            init_body = _dump(init_payload)
            init_headers = _build_headers(ac.secret, "POST", path_msg, init_body, ac.account_id)
            await client.post(url_msg, content=init_body, headers=init_headers, timeout=30)

        elif send_default_system:
            # опциональное техсообщение (по умолчанию выключено, чтобы не засорять чат)
            ts, ts_ms = _now()
            sys_payload: dict[str, Any] = {
                "event_type": "new_message",
                "payload": {
                    "msgid": str(uuid.uuid4()),
                    "timestamp": ts,
                    "msec_timestamp": ts_ms,
                    "conversation_id": conv_id,
                    "sender": {"id": f"tg:{tg_user_id}", "name": tg_user_name or f"tg_{tg_user_id}"},
                    "message": {"type": "text", "text": "🔗 Пользователь открыл бота (инициализация чата)"},
                },
            }
            sys_body = _dump(sys_payload)
            sys_headers = _build_headers(ac.secret, "POST", path_msg, sys_body, ac.account_id)
            await client.post(url_msg, content=sys_body, headers=sys_headers, timeout=30)

    except Exception:
        logger.warning("ensure_chat_created: initial message post failed", exc_info=True)

    return conv_id
