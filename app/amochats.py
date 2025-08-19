import hashlib, hmac, json, time, uuid
from email.utils import formatdate
import httpx
from app.config import settings


class AmoChatsError(Exception): ...

def _base() -> str:
    return "https://amojo.amocrm.ru"


def _dump(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _build_headers(secret: str, method: str, path: str, body: bytes) -> dict:
    date = formatdate(usegmt=True)
    ctype = "application/json"
    md5 = hashlib.md5(body).hexdigest().lower()
    to_sign = "\n".join([method.upper(), md5, ctype, date, path])
    sig = hmac.new(secret.encode("utf-8"), to_sign.encode("utf-8"), hashlib.sha1).hexdigest().lower()
    h = {"Date": date, "Content-Type": ctype, "Content-MD5": md5, "X-Signature": sig}
    if getattr(settings, "AMO_CHATS_ACCOUNT_ID", None):
        h["X-Client-Id"] = settings.AMO_CHATS_ACCOUNT_ID
    return h


async def connect_channel() -> dict:
    """Одноразовое подключение канала (hook_api_version=v2). Можно вызывать повторно — безопасно."""
    if not (settings.AMO_CHATS_CHANNEL_ID and settings.AMO_CHATS_ACCOUNT_ID and settings.AMO_CHATS_SECRET):
        raise AmoChatsError("AmoChats connect: env not configured")

    path = f"/v2/origin/custom/{settings.AMO_CHATS_CHANNEL_ID}/connect"
    url = f"https://amojo.amocrm.ru{path}"
    body = _dump({
        "account_id": settings.AMO_CHATS_ACCOUNT_ID,
        "hook_api_version": "v2",
        "title": getattr(settings, "AMOCHATS_INTEGRATION_NAME", "tg-bridge"),
    })
    headers = _build_headers(settings.AMO_CHATS_SECRET, "POST", path, body)
    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post(url, content=body, headers=headers)
    if r.status_code >= 400:
        raise AmoChatsError(f"connect failed {r.status_code}: {r.text}")
    return r.json() if r.content else {}


async def ensure_amo_chats_connected(logger) -> None:
    if not settings.AMO_CHATS_AUTOCONNECT:
        logger.info("AmoChats autoconnect disabled")
        return
    try:
        await connect_channel()
        logger.info("AmoChats channel connected (v2)")
    except AmoChatsError as e:
        # если уже подключён — Amo обычно вернёт 200/204; на всякий логируем warning
        logger.warning("AmoChats connect warning: %s", e)


async def send_text_from_client(
        *, lead_id: int, text: str,
        tg_user_id: int, tg_user_name: str | None = None,
        conversation_id: str | None = None,
) -> str | None:
    """
    Отправка сообщения как ОТ КЛИЕНТА (TG-пользователь) в канал AmoChats.
    Если conversation_id неизвестен — используем conversation_ref_id='lead:{lead_id}' и amo само создаст/найдёт диалог.
    Возвращает uuid/id разговора (сохраните в TgLink.conversation_id).
    """
    need = [settings.AMO_CHATS_SCOPE_ID, settings.AMO_CHATS_SECRET, settings.AMO_CHATS_ACCOUNT_ID]
    if not all(need):
        raise AmoChatsError("AmoChats env not configured (SCOPE_ID/SECRET/ACCOUNT_ID)")

    path = f"/v2/origin/custom/{settings.AMO_CHATS_SCOPE_ID}"
    url = _base() + path

    now_s = int(time.time())
    now_ms = int(time.time() * 1000)

    # всегда используем conversation_id:
    conv_id = conversation_id or f"lead:{lead_id}"

    payload = {
        "event_type": "new_message",
        "payload": {
            "msgid": str(uuid.uuid4()),
            "timestamp": now_s,  # сек
            "msec_timestamp": now_ms,  # мс
            "conversation_id": conv_id,  # внешний ID диалога
            "sender": {
                "id": f"tg:{tg_user_id}",
                "name": (tg_user_name or f"tg_{tg_user_id}"),
            },
            "message": {"type": "text", "text": text},
        },
    }

    body = _dump(payload)
    headers = _build_headers(settings.AMO_CHATS_SECRET, "POST", path, body)

    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post(url, content=body, headers=headers)

    if r.status_code == 404 or (r.status_code == 400 and "chat not found" in r.text.lower()):
        # редкий случай — сервер ещё не "видит" внешний conv_id.
        # попробуем альтернативно завести через conversation_ref_id:
        alt = payload.copy()
        p = alt["payload"]
        p.pop("conversation_id", None)
        p["conversation_ref_id"] = f"lead:{lead_id}"
        body2 = _dump(alt)
        headers2 = _build_headers(settings.AMO_CHATS_SECRET, "POST", path, body2)
        async with httpx.AsyncClient(timeout=30) as x:
            r = await x.post(url, content=body2, headers=headers2)

    if r.status_code >= 400:
        raise AmoChatsError(f"send_text_from_client failed {r.status_code}: {r.text}")

    data = r.json() if r.content else {}
    conv = (data.get("conversation") or {})
    return conv.get("uuid") or conv.get("id")


async def send_text_from_manager(
        *, conversation_id: str,  # здесь нужен уже существующий uuid/id чата
        user_id: int, user_name: str | None, avatar: str | None,
        text: str,
) -> None:
    """
    Сообщение 'от менеджера' — используем sender.ref_id = AMO_CHATS_SENDER_USER_AMOJO_ID,
    а в receiver кладём данные клиента (опционально).
    """
    need = [settings.AMO_CHATS_SCOPE_ID, settings.AMO_CHATS_SECRET,
            settings.AMO_CHATS_ACCOUNT_ID, settings.AMO_CHATS_SENDER_USER_AMOJO_ID]
    if not all(need):
        raise AmoChatsError("AmoChats env not configured (SCOPE/SECRET/ACCOUNT_ID/SENDER_REF_ID)")

    path = f"/v2/origin/custom/{settings.AMO_CHATS_SCOPE_ID}"
    url = _base() + path

    now_ms = int(time.time() * 1000)
    payload = {
        "event_type": "new_message",
        "payload": {
            "msgid": str(uuid.uuid4()),
            "timestamp": now_ms,
            "msec_timestamp": now_ms,
            "conversation_id": conversation_id,
            "sender": {"ref_id": settings.AMO_CHATS_SENDER_USER_AMOJO_ID},
            "receiver": {
                "id": str(user_id),
                **({"name": user_name} if user_name else {}),
                **({"avatar": avatar} if avatar else {}),
            },
            "message": {"type": "text", "text": text},
        },
    }

    body = _dump(payload)
    headers = _build_headers(settings.AMO_CHATS_SECRET, "POST", path, body)

    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post(url, content=body, headers=headers)
    if r.status_code >= 400:
        raise AmoChatsError(f"send_text_from_manager failed {r.status_code}: {r.text}")
