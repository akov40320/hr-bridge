"""Helper functions used by the survey Telegram bot.

The helpers include utilities for parsing ``/start`` arguments, generating
prompts and summaries for a short survey and formatting Telegram identities.
"""

from aiogram.types import Message


def parse_start_arg(text: str) -> int | None:
    """Extract integer ``/start`` argument from ``text``.

    Returns the integer value if the message starts with ``/start <id>`` and the
    argument can be parsed, otherwise ``None``.
    """

    parts = (text or "").strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0].startswith("/start"):
        try:
            return int(parts[1])
        except ValueError:
            return None
    return None


def survey_prompt(step: int) -> str:
    """Return the prompt for the given survey ``step``."""

    if step == 0:
        return "В каком вы городе?"
    if step == 1:
        return "Опишите кратко опыт по вакансии."
    if step == 2:
        return "Когда вам удобно на связи? (например, завтра после 14:00)"
    return "Спасибо, опрос завершён!"


def survey_summary(city: str | None, experience: str | None, time_pref: str | None) -> str:
    """Compose a summary message using user-provided survey answers."""

    return (
        "Итоги опроса:\n"
        f"• Город: {city or '-'}\n"
        f"• Опыт: {experience or '-'}\n"
        f"• Связь: {time_pref or '-'}"
    )


def pretty_tg_identity(m: Message) -> str:
    """Return a human friendly representation of the Telegram user."""

    user = m.from_user
    if not user:
        return "id:unknown"
    return f"@{user.username}" if user.username else f"id:{user.id}"
