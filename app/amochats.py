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
        tg_user_id: int,  # <--- добавили
        tg_user_name: str | None = None,
        conversation_id: str | None = None,
) -> str | None:
    path = f"/v2/origin/custom/{settings.AMO_CHATS_SCOPE_ID}"
    url = f"https://amojo.amocrm.ru{path}"

    # если знаем uuid — шлём в него; если нет — создадим/найдём по референсу
    conv = {}
    if conversation_id:
        conv_field = {"conversation_id": conversation_id}
    else:
        conv_field = {"conversation_ref_id": f"lead:{lead_id}"}

    payload = {
        "event_type": "new_message",
        "payload": {
            "msgid": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),  # миллисекунды
            **conv_field,
            # ВАЖНО: отправитель — внешний пользователь, а не amojo-user
            "sender": {
                "id": f"tg:{tg_user_id}",
                "name": tg_user_name or f"tg_{tg_user_id}",
            },
            "message": {"type": "text", "text": text},
        },
    }

    body = _dump(payload)
    headers = _build_headers(settings.AMO_CHATS_SECRET, "POST", path, body)
    headers["X-Client-Id"] = settings.AMO_CHATS_ACCOUNT_ID  # лучше явно добавить

    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post(url, content=body, headers=headers)

    if r.status_code >= 400:
        raise AmoChatsError(f"send_text failed {r.status_code}: {r.text}")

    data = r.json() if r.content else {}
    conv = data.get("conversation") or {}
    return conv.get("uuid") or conv.get("id")
