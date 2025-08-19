import hashlib, hmac, json, time, uuid
from email.utils import formatdate
import httpx
from app.config import settings

class AmoChatsError(Exception): ...

def _dump(obj: dict) -> bytes:
    # Компактный JSON — важен для подписи
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

def _build_headers(secret: str, method: str, path: str, body: bytes) -> dict:
    # Canonical string: "METHOD\nMD5\nContent-Type\nDate\nPATH"
    date = formatdate(usegmt=True)
    ctype = "application/json"
    md5 = hashlib.md5(body).hexdigest().lower()
    sign_str = "\n".join([method.upper(), md5, ctype, date, path])
    signature = hmac.new(secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha1).hexdigest().lower()
    return {
        "Date": date,
        "Content-Type": ctype,
        "Content-MD5": md5,
        "X-Signature": signature,
        "X-Client-Id": settings.AMO_CHATS_ACCOUNT_ID,  # явный аккаунт
    }

def _base() -> str:
    # База для amojo API
    return (getattr(settings, "AMO_CHATS_BASE", "") or "https://amojo.amocrm.ru").rstrip("/")

async def connect_channel(title: str | None = None) -> dict:
    """
    Одноразовое подключение канала к аккаунту (или переподключение).
    Требует: AMO_CHATS_CHANNEL_ID, AMO_CHATS_ACCOUNT_ID, AMO_CHATS_SECRET
    """
    if not (settings.AMO_CHATS_CHANNEL_ID and settings.AMO_CHATS_ACCOUNT_ID and settings.AMO_CHATS_SECRET):
        raise AmoChatsError("AmoChats connect: env not configured (CHANNEL_ID/ACCOUNT_ID/SECRET)")

    path = f"/v2/origin/custom/{settings.AMO_CHATS_CHANNEL_ID}/connect"
    url = _base() + path
    body_obj = {
        "account_id": settings.AMO_CHATS_ACCOUNT_ID,
        "hook_api_version": "v2",
        "title": title or getattr(settings, "AMO_CHATS_CHANNEL_TITLE", "HR Bridge"),
    }
    body = _dump(body_obj)
    headers = _build_headers(settings.AMO_CHATS_SECRET, "POST", path, body)

    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post(url, content=body, headers=headers)
    if r.status_code >= 400:
        raise AmoChatsError(f"connect_channel failed {r.status_code}: {r.text}")
    return r.json() if r.content else {"ok": True}

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

    now_ms = int(time.time() * 1000)
    conv_fields = ({"conversation_id": conversation_id} if conversation_id
                   else {"conversation_ref_id": f"lead:{lead_id}"})

    payload = {
        "event_type": "new_message",
        "payload": {
            "msgid": str(uuid.uuid4()),
            "timestamp": now_ms,        # в мс
            "msec_timestamp": now_ms,   # дубль на всякий
            **conv_fields,
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
    if r.status_code >= 400:
        raise AmoChatsError(f"send_text_from_client failed {r.status_code}: {r.text}")

    data = r.json() if r.content else {}
    conv = (data.get("conversation") or {})
    return conv.get("uuid") or conv.get("id")

async def send_text_from_manager(
    *, conversation_id: str,      # здесь нужен уже существующий uuid/id чата
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
            "sender": { "ref_id": settings.AMO_CHATS_SENDER_USER_AMOJO_ID },
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
