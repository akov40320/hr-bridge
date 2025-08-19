# app/amochats.py
import hashlib
import hmac
import json
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


def _dump_body(obj: dict) -> bytes:
    # Без пробелов, тот же байт-поток и для подписи, и для отправки
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _sign(body: bytes) -> str:
    # Amojo custom origin — HMAC-SHA1 по телу запроса
    return hmac.new(settings.AMO_CHATS_SECRET.encode("utf-8"), body, hashlib.sha1).hexdigest()


async def send_text(lead_id: int, text: str, conversation_id: str | None = None) -> str | None:
    """
    Шлём сообщение в AmoChats (amojo custom origin).
    Требуемые ENV:
      AMO_CHATS_SCOPE_ID, AMO_CHATS_SECRET, AMO_CHATS_ACCOUNT_ID, AMO_CHATS_SENDER_USER_AMOJO_ID
    """
    # safety
    if not (settings.AMO_CHATS_SCOPE_ID and settings.AMO_CHATS_SECRET and
            settings.AMO_CHATS_ACCOUNT_ID and settings.AMO_CHATS_SENDER_USER_AMOJO_ID):
        raise AmoChatsError("AmoChats env not configured (scope/secret/account_id/sender_id)")

    url = f"https://amojo.amocrm.ru/v2/origin/custom/{settings.AMO_CHATS_SCOPE_ID}"

    payload = {
        "event_type": "new_message",
        "payload": {
            "msgid": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
            "conversation": {
                # привязка диалога к сделке — client_id == lead_id
                "client_id": str(lead_id)
            },
            "sender": {
                "id": settings.AMO_CHATS_SENDER_USER_AMOJO_ID,  # от какого "менеджера" в чате
                "name": settings.AMOCHATS_INTEGRATION_NAME or "tg-bridge"
            },
            "message": {
                "type": "text",
                "text": text
            }
        }
    }

    # если вы уже знаете uuid диалога — добавьте; иначе amo создаст/найдёт по client_id
    if conversation_id:
        payload["payload"]["conversation"]["uuid"] = conversation_id

    body = _dump_body(payload)
    signature = _sign(body)

    headers = {
        "Content-Type": "application/json",
        # важные заголовки для origin-custom:
        "X-Signature": signature,  # HMAC-SHA1(body)
        "X-Client-Id": settings.AMO_CHATS_ACCOUNT_ID,  # account_id из AmoJo
        # НИКАКОГО Authorization здесь не нужно
    }

    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post(url, content=body, headers=headers)

    if r.status_code >= 400:
        raise AmoChatsError(f"send_text failed {r.status_code}: {r.text}")

    data = r.json() if r.content else {}
    # сервер может вернуть conversation.uuid — сохраним для следующих сообщений
    conv = (data.get("conversation") or {})
    return conv.get("uuid")
