from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from app.core.retry import with_retry


async def tg_send_with_retry(bot: Bot, chat_id: int, text: str) -> None:
    async def send() -> None:
        await bot.send_message(chat_id=chat_id, text=text)

    def _is_retryable(exc: Exception):
        if isinstance(exc, TelegramRetryAfter):
            return exc.retry_after
        if isinstance(exc, TelegramAPIError):
            return True
        return False

    await with_retry(send, attempts=7, is_retryable=_is_retryable)
