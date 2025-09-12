"""Утилита для повторных попыток корутин с экспоненциальной задержкой."""

import asyncio
from typing import Awaitable, Callable, TypeVar, Union

T = TypeVar("T")
RetryCheck = Callable[[Exception], Union[bool, float]]


async def with_retry(
    coro: Callable[[], Awaitable[T]],
    attempts: int,
    is_retryable: RetryCheck,
) -> T:
    """Выполнить ``coro`` с экспоненциальной задержкой между попытками.

    ``is_retryable`` должен вернуть либо ``True`` — использовать
    экспоненциальную задержку; ``False`` — прекратить попытки и пробросить
    исключение; или ``float`` — задать пользовательскую задержку перед
    следующей попыткой.
    """
    backoff = 0.5
    for attempt in range(attempts):
        try:
            return await coro()
        except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            delay = is_retryable(e)
            if delay is False or attempt == attempts - 1:
                raise
            if isinstance(delay, (int, float)):
                await asyncio.sleep(delay)
            else:
                await asyncio.sleep(backoff)
                backoff *= 2
    raise RuntimeError("with_retry exhausted attempts")
