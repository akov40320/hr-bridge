"""Utilities for sending messages through Telegram with retry support."""

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from app.core.retry import with_retry


async def tg_send_with_retry(bot: Bot, chat_id: int, text: str) -> None:
    """Send ``text`` to ``chat_id`` via *bot*, retrying on transient failures."""

    async def send() -> None:
        """Perform the actual API call to send the message."""
        await bot.send_message(chat_id=chat_id, text=text)

    def _is_retryable(exc: Exception):
        """Return delay or True if *exc* should trigger a retry."""
        if isinstance(exc, TelegramRetryAfter):
            return exc.retry_after
        if isinstance(exc, TelegramAPIError):
            return True
        return False

    await with_retry(send, attempts=7, is_retryable=_is_retryable)
