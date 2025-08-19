import hashlib, hmac, json, time, uuid, httpx
from email.utils import formatdate
from app.config import settings


class AmoChatsError(Exception):
    ...


def _dump(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _build_headers(secret: str, method: str, path: str, body: bytes) -> dict:
    # Required by Chats API: Date, Content-Type, Content-MD5, X-Signature
    # Signature = HMAC-SHA1 over "METHOD\nMD5\nContent-Type\nDate\nPATH"
    date = formatdate(usegmt=True)
    content_type = "application/json"
    md5 = hashlib.md5(body).hexdigest().lower()
    sign_str = "\n".join([method.upper(), md5, content_type, date, path])
    signature = hmac.new(secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha1).hexdigest().lower()
    return {
        "Date": date,
        "Content-Type": content_type,
        "Content-MD5": md5,
        "X-Signature": signature,
        # "X-Client-Id": settings.AMO_CHATS_ACCOUNT_ID,  # не обязателен
    }


async def send_text(
    lead_id: int,
    text: str,
    *,
    conversation_id: str | None = None,        # <-- ДОБАВИЛИ
    conversation_ref_id: str | None = None,    # UUID чата amo (из входящего v2-хука)
) -> str | None:
    need = [
        settings.AMO_CHATS_SCOPE_ID,
        settings.AMO_CHATS_SECRET,
        settings.AMO_CHATS_SENDER_USER_AMOJO_ID,
    ]
    if not all(need):
        raise AmoChatsError("AmoChats env not configured (scope/secret/sender_id)")

    path = f"/v2/origin/custom/{settings.AMO_CHATS_SCOPE_ID}"
    url = f"https://amojo.amocrm.ru{path}"

    now = time.time()
    body_obj = {
        "event_type": "new_message",
        "payload": {
            "msgid": str(uuid.uuid4()),
            "timestamp": int(now),
            "msec_timestamp": int(now * 1000),
            # если знаем UUID amo-чата — передаём его;
            # иначе используем внешний conversation_id (явно переданный или lead:{lead_id})
            **({"conversation_ref_id": conversation_ref_id} if conversation_ref_id else {}),
            **({"conversation_id": conversation_id} if conversation_id else {"conversation_id": f"lead:{lead_id}"}),
            "sender": {
                "id": settings.AMO_CHATS_SENDER_USER_AMOJO_ID,
                "name": getattr(settings, "AMO_CHATS_SENDER_NAME",
                                getattr(settings, "AMOCHATS_INTEGRATION_NAME", "tg-bridge")),
            },
            "message": {"type": "text", "text": text},
        },
    }

    body = _dump(body_obj)
    headers = _build_headers(settings.AMO_CHATS_SECRET, "POST", path, body)  # твоя функция подписи по канон. строке

    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post(url, content=body, headers=headers)

    if r.status_code >= 400:
        raise AmoChatsError(f"send_text failed {r.status_code}: {r.text}")

    data = r.json() if r.content else {}
    conv = data.get("conversation") or {}
    return conv.get("uuid") or conv.get("id")
