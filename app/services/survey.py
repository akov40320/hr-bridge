"""Вспомогательные функции, используемые Telegram‑ботом опроса.

Сюда входят утилиты для разбора аргумента ``/start``, генерации
подсказок и итогов короткого опроса, а также форматирования идентификаторов Telegram.
"""

from aiogram.types import Message

from app.core.config import get_settings
from app.services.queue import rabbitmq, RabbitMQClient


def parse_start_arg(text: str) -> int | None:
    """Извлечь целочисленный аргумент ``/start`` из ``text``.

    Возвращает целое значение, если сообщение начинается с ``/start <id>`` и
    аргумент успешно парсится; иначе возвращает ``None``.
    """

    parts = (text or "").strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0].startswith("/start"):
        try:
            return int(parts[1])
        except ValueError:
            return None
    return None


def survey_prompt(step: int) -> str:
    """Вернуть подсказку для указанного шага опроса ``step``."""

    if step == 0:
        return "В каком вы городе?"
    if step == 1:
        return "Опишите кратко опыт по вакансии."
    if step == 2:
        return "Когда вам удобно на связи? (например, завтра после 14:00)"
    return "Спасибо, опрос завершён!"


def survey_summary(city: str | None, experience: str | None, time_pref: str | None) -> str:
    """Сформировать итоговое сообщение на основе ответов пользователя."""

    return (
        "Итоги опроса:\n"
        f"• Город: {city or '-'}\n"
        f"• Опыт: {experience or '-'}\n"
        f"• Связь: {time_pref or '-'}"
    )


def pretty_tg_identity(m: Message) -> str:
    """Вернуть человеко‑читаемое представление пользователя Telegram."""

    user = m.from_user
    if not user:
        return "id:unknown"
    return f"@{user.username}" if user.username else f"id:{user.id}"


async def mark_went_to_bot_async(
    lead_id: int,
    bot_kind: str,
    identity: str,
    queue_client: RabbitMQClient = rabbitmq,
):
    """Переносим на воркер: добавляем заметку и тег через RMQ."""
    s = get_settings()

    await queue_client.publish_task({
        "platform": "amo",
        "action": "amo_add_note",
        "lead_id": lead_id,
        "text": f"[{bot_kind}] Кандидат перешёл в бота (TG {identity}).",
    })
    await queue_client.publish_task({
        "platform": "amo",
        "action": "amo_add_tags",
        "lead_id": lead_id,
        "tags": [s.AMO_TAG_WENT_TO_BOT],
    })
    stage_id = (
        s.AMO_STAGE_ID_MASTER_NEW
        if bot_kind == "master"
        else s.AMO_STAGE_ID_OPERATOR_NEW
    )
    await queue_client.publish_task(
        {
            "platform": "amo",
            "action": "amo_update_status",
            "lead_id": lead_id,
            "status_id": stage_id,
        }
    )
