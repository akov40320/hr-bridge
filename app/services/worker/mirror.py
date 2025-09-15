"""Обработчики, зеркалирующие сообщения между AMO CRM и Telegram-ботами.

Модуль предоставляет асинхронные обработчики воркера для пересылки
сообщений из AMO CRM в Telegram, обратной передачи сообщений из Telegram в
AMO и отправки сообщений, созданных ботом, в чаты AMO. Все обработчики
принимают словарь ``payload`` с деталями, зависящими от направления зеркала.
"""

import logging
from typing import Optional, cast, Any
from aiogram import Bot

from app.adapters.amochats import send_text_from_manager, ensure_chat_created, send_text_from_client
from app.core.config import get_settings
from app.services.dedup import check_and_store, calc_key
from app.store_chat import set_conversation
from app.services import tg_send_with_retry
from app.core.retry import with_retry
from app.http_client import get_http_client
from app.adapters.amo_client import AmoClient
from app.services.queue import rabbitmq

logger = logging.getLogger(__name__)


def _as_int_maybe(x: Any) -> int | None:
    """Безопасно привести к int или вернуть None, если невозможно."""
    if isinstance(x, int):
        return x
    if isinstance(x, str):
        try:
            return int(x)
        except ValueError:
            return None
    return None


async def handle_mirror_amo_to_tg(payload: dict):
    """Переслать сообщение из AMO CRM пользователю Telegram.

    Аргументы:
        payload: словарь с деталями сообщения. Ожидаются ключи
            ``bot_kind`` (``"master"`` или ``"operator"``) для выбора бота,
            ``user_id`` — получатель в Telegram,
            ``text`` — текст сообщения,
            опционально ``msg_key`` для дедупликации.

    Поведение:
        Использует соответствующего бота Telegram для доставки текста.
        Если указан ``msg_key`` и он уже обработан, сообщение пропускается.

    Возвращает:
        None
    """
    msg_key = payload.get("msg_key") or ""
    if msg_key:
        _uid_for_dedup = _as_int_maybe(payload.get("user_id"))
        if _uid_for_dedup is not None:
            msg_key = f"to_tg:{msg_key}:{payload.get('bot_kind')}:{_uid_for_dedup}"
        dedup = calc_key("mirror", msg_key)
        if not await check_and_store(dedup):
            logger.info("mirror: дубликат %s -> пропуск", dedup)
            return

    bot_kind = payload["bot_kind"]
    user_id = int(payload["user_id"])
    text = payload["text"]

    s = get_settings()
    token = s.TELEGRAM_MASTER_BOT_TOKEN if bot_kind == "master" else s.TELEGRAM_OPERATOR_BOT_TOKEN
    if not token:
        raise RuntimeError(f"Telegram bot '{bot_kind}' is not configured")

    async with Bot(token) as bot:
        await tg_send_with_retry(bot, user_id, text)


async def handle_mirror_tg_to_amo(payload: dict):  # pylint: disable=too-many-locals
    """Зеркалировать сообщение Telegram в AMO CRM (как реальное сообщение в чат сделки)."""
    msg_key = payload.get("msg_key") or ""
    if msg_key:
        dedup = calc_key("mirror", msg_key)
        if not await check_and_store(dedup):
            logger.info("mirror: дубликат %s -> пропуск", dedup)
            return

    lead_id = int(payload["lead_id"])
    text = payload["text"]
    tg_user_id = int(payload["tg_user_id"])
    tg_user_name = payload.get("tg_user_name")
    conv_id: Optional[str] = payload.get("conversation_id")
    bot_kind_val = payload.get("bot_kind")
    if not isinstance(bot_kind_val, str):
        raise RuntimeError("bot_kind is required")
    bot_kind = bot_kind_val

    http_client = get_http_client()
    amo = await AmoClient.create(http_client)

    # (опционально) оставляем заметку для аудита
    # await with_retry(
    #     lambda: amo.add_note(lead_id, f"[TG->{bot_kind}] {text}"),
    #     attempts=6,
    #     is_retryable=lambda e: True,
    # )

    # 👇 КЛЮЧЕВОЕ: если нет conversation_id — создаём/привязываем чат к контакту сделки
    if not conv_id:
        contact_id: int | None = None
        try:
            lead = await amo.get_lead_with_contacts(lead_id)
            emb = (lead or {}).get("_embedded") or {}
            contacts = emb.get("contacts") or []
            if contacts:
                contact_id = int(contacts[0]["id"])
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning("не удалось получить контакт для лида %s", lead_id, exc_info=True)

        # Создаём чат вида conversation_id="lead:<lead_id>" и ПРИВЯЗЫВАЕМ к контакту
        conv_id = await with_retry(
            lambda: ensure_chat_created(
                lead_id=lead_id,
                contact_id=contact_id,
                bind_contact_id=contact_id,   # <-- без этого чат не появится в карточке
                tg_user_id=tg_user_id,
                tg_user_name=tg_user_name,
                client=http_client,
                # init_text/ init_as_manager НЕ ставим: это сообщение от клиента
            ),
            attempts=6,
            is_retryable=lambda e: True,
        )
        # сохраняем conversation_id, если он только что появился
        assert isinstance(conv_id, str)
        await set_conversation(tg_user_id, bot_kind, conv_id)

    # Теперь отправляем как КЛИЕНТСКОЕ сообщение в чат сделки
    new_cid = await with_retry(
        lambda: send_text_from_client(
            lead_id=lead_id,
            text=text,
            tg_user_id=tg_user_id,
            tg_user_name=tg_user_name,
            conversation_id=conv_id,
            client=http_client,
        ),
        attempts=6,
        is_retryable=lambda e: True,
    )

    # Сохраняем новый conversation_id, если он изменился
    if new_cid is not None and new_cid != conv_id:
        await set_conversation(tg_user_id, bot_kind, cast(str, new_cid))


async def handle_mirror_bot_to_amo(payload: dict):  # pylint: disable=too-many-locals
    """Переслать сообщение, сгенерированное ботом, в чат AMO.

    Аргументы:
        payload: содержит ``text`` и ``user_id``. Дополнительные ключи:
            ``user_name``, ``conversation_id``, ``lead_id`` и ``msg_key``
            для дедупликации.

    Поведение:
        Убеждается, что для пользователя Telegram существует чат AMO и
        отправляет текст как сообщение менеджера. Дублирующиеся payload
        игнорируются, если ``msg_key`` уже обработан.

    Возвращает:
        None
    """
    msg_key = payload.get("msg_key") or ""
    if msg_key:
        dedup = calc_key("mirror", msg_key)
        if not await check_and_store(dedup):
            logger.info("mirror: дубликат %s -> пропуск", dedup)
            return

    text = payload["text"]
    user_id = int(payload["user_id"])
    user_name = payload.get("user_name")
    conv_id: Optional[str] = payload.get("conversation_id")
    lead_id = payload.get("lead_id")
    status_id = payload.get("status_id")
    bot_kind = payload.get("bot_kind")

    http_client = get_http_client()

    if not conv_id and lead_id:
        contact_id: int | None = None
        try:
            amo = await AmoClient.create(http_client)
            lead = await amo.get_lead_with_contacts(int(lead_id))
            emb = (lead or {}).get("_embedded") or {}
            contacts = emb.get("contacts") or []
            if contacts:
                contact_id = int(contacts[0]["id"])
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning("не удалось получить контакт для лида %s", lead_id, exc_info=True)

        conv_id = await with_retry(
            lambda: ensure_chat_created(
                lead_id=int(lead_id),
                contact_id=contact_id,
                bind_contact_id=contact_id,
                tg_user_id=user_id,
                tg_user_name=user_name,
                client=http_client,
            ),
            attempts=6,
            is_retryable=lambda e: True,
        )

        if isinstance(bot_kind, str):
            await set_conversation(user_id, bot_kind, cast(str, conv_id))

        if status_id is not None:
            dedup = calc_key("chat_status", f"{lead_id}:{status_id}")
            if await check_and_store(dedup):
                await rabbitmq.publish_task(
                    {
                        "platform": "amo",
                        "action": "amo_update_status",
                        "lead_id": int(lead_id),
                        "status_id": int(status_id),
                    }
                )

    if not conv_id:
        raise RuntimeError("bot_to_amo: no conversation_id and no lead_id to create one")

    await with_retry(
        lambda: send_text_from_manager(
            conversation_id=conv_id,
            user_id=user_id,
            user_name=user_name,
            avatar=None,
            text=text,
            client=http_client,
        ),
        attempts=6,
        is_retryable=lambda e: True,
    )
