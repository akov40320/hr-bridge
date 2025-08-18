# app/amochats.py
import time, uuid
import httpx
from app.config import settings


class AmoChatsError(Exception):
    ...


def _endpoint() -> str:
    base = settings.AMO_CHATS_BASE.rstrip("/")
    return f"{base}/v2/origin/custom/{settings.AMO_CHATS_SCOPE_ID}"


def _headers() -> dict:
    # Для custom origin обычно достаточно Bearer.
    # Если в твоей интеграции требуют X-Account-Id — раскомментируй.
    h = {
        "Authorization": f"Bearer {settings.AMO_CHATS_SECRET}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    # h["X-Account-Id"] = settings.AMO_CHATS_ACCOUNT_ID
    return h


async def send_text(lead_id: int, text: str, conversation_id: str | None = None) -> str | None:
    if not settings.AMOCHATS_ENABLED:
        return None

    payload: dict = {
        "event_type": "new_message",
        "payload": {
            "timestamp": int(time.time()),
            "channel_id": settings.AMO_CHATS_CHANNEL_ID,
            "message": {
                "id": str(uuid.uuid4()),
                "type": "text",
                "text": text,
            },
            "sender": {
                "id": settings.AMO_CHATS_SENDER_USER_AMOJO_ID,
                "name": "Recruiting Bridge",
                "type": "manager",  # важно: сообщение «от менеджера»
            },
        },
    }

    # Продолжить существующую беседу по uuid или открыть новую по client_id
    if conversation_id:
        payload["payload"]["conversation"] = {"uuid": conversation_id}
    else:
        payload["payload"]["conversation"] = {"client_id": str(lead_id)}

    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post(_endpoint(), json=payload, headers=_headers())
    if r.status_code >= 400:
        raise AmoChatsError(f"send_text failed {r.status_code}: {r.text}")

    data = r.json() if r.content else {}
    # В разных конфигурациях custom origin в ответе могут вернуть conversation.uuid
    conv = (data.get("payload") or {}).get("conversation") if isinstance(data, dict) else None
    conv_id = (conv or {}).get("uuid") if isinstance(conv, dict) else None

    return conv_id or conversation_id

