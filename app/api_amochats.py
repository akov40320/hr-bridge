from fastapi import APIRouter, Request, Response
from app.store_chat import get_by_lead, get_by_conversation
from aiogram import Bot
from app.config import settings

router_amo_chats = APIRouter()

# Боты для ответной пересылки в TG (если хочешь форвардить в обе группы ботов)
tg_master = Bot(settings.TELEGRAM_MASTER_BOT_TOKEN) if settings.TELEGRAM_MASTER_BOT_TOKEN else None
tg_operator = Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN) if settings.TELEGRAM_OPERATOR_BOT_TOKEN else None


@router_amo_chats.post("/webhooks/amo-chats/in")
async def amochats_in(request: Request):
    # подпись, если включена
    if settings.AMOCHATS_INCOMING_SECRET:
        if request.headers.get("X-AmoChats-Signature") != settings.AMOCHATS_INCOMING_SECRET:
            return Response(status_code=401)

    data = await request.json()
    if not isinstance(data, dict):
        return {"ok": False, "error": "bad json"}

    # фильтруем только новые сообщения клиента
    if data.get("event_type") != "new_message":
        return {"ok": True}

    payload = data.get("payload") or {}
    msg = (payload.get("message") or {})
    text = msg.get("text") or ""
    if not text:
        return {"ok": True}  # нечего форвардить

    conv = (payload.get("conversation") or {})
    conv_uuid = conv.get("uuid")
    client_id = conv.get("client_id")

    # пробуем lead_id из client_id
    lead_id = None
    try:
        if client_id:
            lead_id = int(client_id)
    except Exception:
        lead_id = None

    links = []
    if lead_id:
        links = await get_by_lead(lead_id)
    elif conv_uuid:
        links = await get_by_conversation(conv_uuid)

    # отправляем всем связанным TG-пользователям (master/operator)
    for ln in links or []:
        if ln.bot_kind == "master" and tg_master:
            try:
                await tg_master.send_message(chat_id=ln.user_id, text=f"[Amo] {text}")
            except Exception as e:
                print("TG send (master) err:", e)
        if ln.bot_kind == "operator" and tg_operator:
            try:
                await tg_operator.send_message(chat_id=ln.user_id, text=f"[Amo] {text}")
            except Exception as e:
                print("TG send (operator) err:", e)

    return {"ok": True}