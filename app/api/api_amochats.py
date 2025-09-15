"""Обработчики вебхуков AmoChats и связанные вспомогательные функции."""
# pylint: disable=fixme
import hashlib
import hmac
import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.adapters.amochats import connect_channel
from app.core.config import get_settings
from app.core.guards import require_admin
from app.http_client import get_http_client
from app.services.dedup import calc_key, check_and_store
from app.services.queue import RabbitMQClient, rabbitmq
from app.store_chat import (
    get_by_conversation,
    get_by_lead,
    get_by_user,
    set_conversation,
)

logger = logging.getLogger(__name__)
router_amo_chats = APIRouter()


async def verify_amochats_signature(
        request: Request,
        settings=Depends(get_settings),
) -> None:
    """Проверить подпись вебхука AmoChats и сохранить сырое тело запроса."""
    raw = await request.body()

    request.state.raw_body = raw

    # Temporary bypass for development/testing (controlled by AMOCHATS_SKIP_SIGNATURE)
    if getattr(settings, "AMOCHATS_SKIP_SIGNATURE", False):
        logger.warning(
            (
                "Проверка подписи AmoChats ОТКЛЮЧЕНА через "
                "переменную AMOCHATS_SKIP_SIGNATURE"
            )
        )
        return

    # Простейшая проверка подписи HMAC-SHA1 (см. TODO ниже для будущих улучшений)
    x_sig = request.headers.get("X-Signature")
    calc = hmac.new(
        settings.AMO_CHATS_SECRET.encode("utf-8"), raw, hashlib.sha1
    ).hexdigest()
    if not x_sig or not hmac.compare_digest(x_sig.lower(), calc.lower()):
        raise HTTPException(status_code=401)

    # TODO: подпись
    # x_sig = request.headers.get("X-Signature")
    # calc = hmac.new(
    #     settings.AMO_CHATS_SECRET.encode("utf-8"), raw, hashlib.sha1
    # ).hexdigest()
    # if not x_sig or not hmac.compare_digest(x_sig.lower(), calc.lower()):
    #     raise HTTPException(status_code=401)


def parse_lead_id(client_id: str) -> int | None:
    """Извлечь числовой идентификатор сделки из строки ``lead:<id>``."""
    if isinstance(client_id, str) and client_id.startswith("lead:"):
        try:
            return int(client_id.split(":", 1)[1])
        except ValueError:
            return None
    return None


async def parse_json(
        request: Request, raw: bytes, scope_id: str | None
) -> dict | None:
    """Вернуть тело JSON; при ошибке декодирования записать в лог."""
    try:
        return await request.json()
    except ValueError:
        txt = raw[:500].decode("utf-8", "ignore")
        logger.warning("amo-chats некорректный JSON (scope_id=%s); body=%r", scope_id, txt)
        return None


def extract_message(data: dict) -> tuple[str, str | None, str, dict, dict, str]:
    """Извлечь информацию о сообщении из тела вебхука."""
    root = data.get("message") or data.get("payload") or {}
    msg = root.get("message") or {}
    text = (msg.get("text") or "").strip()
    conv = root.get("conversation") or {}
    conv_ref_id = conv.get("id") or conv.get("uuid")
    client_id = conv.get("client_id") or ""
    sender = root.get("sender") or {}
    receiver = root.get("receiver") or {}
    msg_id = (
            root.get("msgid")
            or msg.get("id")
            or msg.get("uuid")
            or msg.get("message_id")
            or ""
    )
    return text, conv_ref_id, client_id, sender, receiver, msg_id


async def set_conv_for_links(links, conv_ref_id: str) -> None:
    """Обновить связи, проставив идентификатор беседы."""
    for ln in links:
        if not ln.conversation_id:
            await set_conversation(ln.user_id, ln.bot_kind, conv_ref_id)


def parse_tg_uid(ext_id: str) -> int | None:
    """Извлечь Telegram user id из внешнего идентификатора ``tg:<id>``."""
    if isinstance(ext_id, str) and ext_id.startswith("tg:"):
        try:
            return int(ext_id.split(":", 1)[1])
        except ValueError:
            logger.warning("amo-chats: не удалось распарсить tg uid из ext_id %r", ext_id)
    return None


async def links_from_ext_id(
        conv_ref_id: str | None, sender: dict, receiver: dict
):
    """Вернуть связи чата по внешнему идентификатору (например, Telegram UID)."""
    ext_id = (
            sender.get("client_id")
            or sender.get("id")
            or receiver.get("client_id")
            or receiver.get("id")
            or ""
    )
    tg_uid = parse_tg_uid(ext_id)
    if not tg_uid:
        return []
    cand = []
    ln1 = await get_by_user(tg_uid, "master")
    if ln1:
        cand.append(ln1)
    ln2 = await get_by_user(tg_uid, "operator")
    if ln2:
        cand.append(ln2)
    links = [ln for ln in cand if not ln.conversation_id] or cand
    if links and conv_ref_id:
        await set_conv_for_links(links, conv_ref_id)
    return links


async def resolve_links(
        conv_ref_id: str | None,
        client_conv_id: str | None,
        lead_id: int | None,
        sender: dict,
        receiver: dict,
):
    """Определить связи по ID беседы, привязке сделки или внешним идентификаторам."""
    links = []
    if conv_ref_id:
        links = await get_by_conversation(conv_ref_id)
    if not links and client_conv_id:
        links = await get_by_conversation(client_conv_id)
    if not links and lead_id:
        links = await get_by_lead(lead_id)
        target_conv = conv_ref_id or client_conv_id
        if links and target_conv:
            await set_conv_for_links(links, target_conv)
    if not links:
        links = await links_from_ext_id(conv_ref_id or client_conv_id, sender, receiver)
    return links


async def publish_links(
        queue_client: RabbitMQClient,
        links,
        conv_ref_id: str | None,
        msg_id: str,
        text: str,
) -> None:
    """Опубликовать зеркальные сообщения в очередь для каждой связи."""
    # Выбираем по одному активному получателю на каждый bot_kind (максимальный updated_at)
    selected_by_kind: dict[str, object] = {}
    for ln in links or []:
        kind = getattr(ln, "bot_kind", None)
        if not isinstance(kind, str):
            continue
        prev = selected_by_kind.get(kind)
        cur_ts = getattr(ln, "updated_at", None) or datetime.min
        prev_ts = getattr(prev, "updated_at", None) if prev is not None else None
        prev_ts = prev_ts or datetime.min
        if prev is None or cur_ts > prev_ts:
            selected_by_kind[kind] = ln
    for ln in selected_by_kind.values():
        key_src = (
            f"amo:{conv_ref_id}:{msg_id or hashlib.sha256((text or '').encode()).hexdigest()[:16]}"
        )
        await queue_client.publish_task(
            {
                "platform": "mirror",
                "action": "amo_to_tg",
                "bot_kind": ln.bot_kind,
                "user_id": ln.user_id,
                "text": text,
                "msg_key": key_src,
            }
        )


async def is_duplicate(raw: bytes) -> bool:
    """Проверить, обрабатывался ли уже этот входящий payload."""
    key = calc_key("amo_chats", raw)
    return not await check_and_store(key)


@router_amo_chats.post("/webhooks/amo-chats/in/{scope_id}",
                       dependencies=[Depends(verify_amochats_signature)])
async def amochats_in(
        request: Request,
        scope_id: str,
        queue_client: RabbitMQClient = Depends(lambda: rabbitmq),
):
    """Обработать входящий вебхук AmoChats и зеркалировать сообщения в Telegram."""
    raw = getattr(request.state, "raw_body", await request.body())

    if await is_duplicate(raw):
        logger.info("amo-chats: дубликат вебхука пропущен (scope_id=%s)", scope_id)
        return {"ok": True, "duplicate": True}

    data = await parse_json(request, raw, scope_id)
    if data is None:
        return {"ok": False, "error": "bad json"}

    text, conv_ref_id, client_id, sender, receiver, msg_id = extract_message(data)
    if not text:
        return {"ok": True}

    logger.info(
        "amo-chats IN: scope=%s conv_id=%s client_id=%s text_len=%d",
        scope_id,
        conv_ref_id,
        client_id,
        len(text),
    )

    lead_id = parse_lead_id(client_id)
    links = await resolve_links(conv_ref_id, client_id, lead_id, sender, receiver)

    logger.info(
        "amo-chats: найдено ссылок: %d (conv=%s client_conv=%s lead=%s)",
        len(links),
        conv_ref_id,
        client_id,
        lead_id,
    )

    await publish_links(queue_client, links, conv_ref_id, msg_id, text)

    logger.info(
        "amo-chats -> RMQ: зеркалирование успешно (scope_id=%s, text_len=%d)",
        scope_id,
        len(text),
    )
    return {"ok": True}


# --- Админ для одноразового /connect ---
amo_admin = APIRouter(
    prefix="/admin/amo-chats", dependencies=[Depends(require_admin)]
)


@amo_admin.post("/connect")
async def admin_connect(http_client: httpx.AsyncClient = Depends(get_http_client)):
    """Инициировать одноразовое подключение к AmoChats из админ‑панели."""
    resp = await connect_channel(http_client)
    return {"ok": True, "response": resp}
