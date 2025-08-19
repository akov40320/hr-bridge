import hashlib, hmac, json, time, uuid, httpx
from app.config import settings


class AmoChatsError(Exception): ...


def _dump_body(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _sign(body: bytes) -> str:
    return hmac.new(settings.AMO_CHATS_SECRET.encode("utf-8"), body, hashlib.sha1).hexdigest()


async def send_text(lead_id: int, text: str, conversation_id: str | None = None) -> str | None:
    if not (settings.AMO_CHATS_SCOPE_ID and settings.AMO_CHATS_SECRET and
            settings.AMO_CHATS_ACCOUNT_ID and settings.AMO_CHATS_SENDER_USER_AMOJO_ID):
        raise AmoChatsError("AmoChats env not configured (scope/secret/account_id/sender_id)")

    url = f"https://amojo.amocrm.ru/v2/origin/custom/{settings.AMO_CHATS_SCOPE_ID}"
    payload = {
        "event_type": "new_message",
        "payload": {
            "msgid": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
            "conversation": {"client_id": str(lead_id)},
            "sender": {
                "id": settings.AMO_CHATS_SENDER_USER_AMOJO_ID,
                "name": getattr(settings, "AMO_CHATS_SENDER_NAME",
                                getattr(settings, "AMOCHATS_INTEGRATION_NAME", "tg-bridge")),
            },
            "message": {"type": "text", "text": text},
        },
    }
    if conversation_id:
        payload["payload"]["conversation"]["uuid"] = conversation_id

    body = _dump_body(payload)
    headers = {
        "Content-Type": "application/json",
        "X-Signature": _sign(body),
        "X-Client-Id": settings.AMO_CHATS_ACCOUNT_ID,
    }

    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post(url, content=body, headers=headers)
    if r.status_code >= 400:
        raise AmoChatsError(f"send_text failed {r.status_code}: {r.text}")

    data = r.json() if r.content else {}
    return (data.get("conversation") or {}).get("uuid")
