import asyncio
from typing import Callable, Awaitable, TypeVar, Union

T = TypeVar("T")
RetryCheck = Callable[[Exception], Union[bool, float]]


async def with_retry(coro: Callable[[], Awaitable[T]], attempts: int, is_retryable: RetryCheck) -> T:
    """Execute ``coro`` with exponential backoff.

    ``is_retryable`` should return either ``True`` to use exponential backoff
    delay, ``False`` to stop retrying and re-raise the exception, or a ``float``
    specifying a custom delay before the next attempt.
    """
    backoff = 0.5
    for attempt in range(attempts):
        try:
            return await coro()
        except Exception as e:  # noqa: BLE001 - propagate non retryable errors
            delay = is_retryable(e)
            if delay is False or attempt == attempts - 1:
                raise
            if isinstance(delay, (int, float)):
                await asyncio.sleep(delay)
            else:
                await asyncio.sleep(backoff)
                backoff *= 2
    raise RuntimeError("with_retry exhausted attempts")
