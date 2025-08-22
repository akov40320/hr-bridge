import asyncio
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter


async def tg_send_with_retry(bot: Bot, chat_id: int, text: str):
    backoff = 0.5
    for _ in range(7):
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            return
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramAPIError:
            if backoff > 8:
                raise
            await asyncio.sleep(backoff)
            backoff *= 2
