from aiogram.types import Message

from app.core.config import get_settings
from app.services.queue import rabbitmq, RabbitMQClient


def parse_start_arg(text: str) -> int | None:
    parts = (text or "").strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0].startswith("/start"):
        try:
            return int(parts[1])
        except Exception:
            return None
    return None


def survey_prompt(step: int) -> str:
    if step == 0:
        return "В каком вы городе?"
    if step == 1:
        return "Опишите кратко опыт по вакансии."
    if step == 2:
        return "Когда вам удобно на связи? (например, завтра после 14:00)"
    return "Спасибо, опрос завершён!"


def survey_summary(city: str | None, experience: str | None, time_pref: str | None) -> str:
    return (
        "Итоги опроса:\n"
        f"• Город: {city or '-'}\n"
        f"• Опыт: {experience or '-'}\n"
        f"• Связь: {time_pref or '-'}"
    )


def pretty_tg_identity(m: Message) -> str:
    return f"@{m.from_user.username}" if m.from_user.username else f"id:{m.from_user.id}"


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
