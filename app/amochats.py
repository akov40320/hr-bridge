import hashlib, hmac, json, time, uuid, httpx
from app.config import settings


class AmoChatsError(Exception): ...


def _dump(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _sign(body: bytes) -> str:
    return hmac.new(settings.AMO_CHATS_SECRET.encode("utf-8"), body, hashlib.sha1).hexdigest()


async def send_text(lead_id: int, text: str, conversation_id: str | None = None) -> str | None:
    # sanity
    need = [settings.AMO_CHATS_SCOPE_ID, settings.AMO_CHATS_SECRET,
            settings.AMO_CHATS_ACCOUNT_ID, settings.AMO_CHATS_SENDER_USER_AMOJO_ID]
    if not all(need):
        raise AmoChatsError("AmoChats env not configured (scope/secret/account_id/sender_id)")

    url = f"https://amojo.amocrm.ru/v2/origin/custom/{settings.AMO_CHATS_SCOPE_ID}"

    conversation: dict = {}
    if conversation_id:
        # уже знаем uuid беседы → адресуемся напрямую
        conversation["conversation_id"] = conversation_id
    else:
        # первый месседж → создаём/ищем по рефу
        # реф можно выбрать любой стабильный. берём lead:<lead_id>
        conversation["conversation_ref_id"] = f"lead:{lead_id}"

    payload = {
        "event_type": "new_message",
        "payload": {
            "msgid": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
            "conversation": conversation,
            "sender": {
                "id": settings.AMO_CHATS_SENDER_USER_AMOJO_ID,
                "name": getattr(settings, "AMO_CHATS_SENDER_NAME",
                                getattr(settings, "AMOCHATS_INTEGRATION_NAME", "tg-bridge")),
            },
            "message": {"type": "text", "text": text},
        },
    }

    body = _dump(payload)
    headers = {
        "Content-Type": "application/json",
        "X-Signature": _sign(body),  # HMAC-SHA1(body) по SECRET
        "X-Client-Id": settings.AMO_CHATS_ACCOUNT_ID,  # account_id (UUID) из AmoJo
    }

    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post(url, content=body, headers=headers)

    if r.status_code >= 400:
        raise AmoChatsError(f"send_text failed {r.status_code}: {r.text}")

    data = r.json() if r.content else {}
    return (data.get("conversation") or {}).get("uuid")
