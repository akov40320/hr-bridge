"""Утилиты для отправки сообщений в Telegram с поддержкой повторов."""

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from app.core.retry import with_retry


async def tg_send_with_retry(bot: Bot, chat_id: int, text: str) -> None:
    """Отправить ``text`` в ``chat_id`` через *bot*, повторяя при временных сбоях."""

    async def send() -> None:
        """Выполнить фактический вызов API для отправки сообщения."""
        await bot.send_message(chat_id=chat_id, text=text)

    def _is_retryable(exc: Exception):
        """Вернуть задержку или True, если *exc* должен приводить к повтору."""
        if isinstance(exc, TelegramRetryAfter):
            return exc.retry_after
        if isinstance(exc, TelegramAPIError):
            return True
        return False

    await with_retry(send, attempts=7, is_retryable=_is_retryable)
