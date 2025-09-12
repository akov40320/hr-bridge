"""Утилиты для выполнения асинхронных HTTP‑запросов.

Модуль предоставляет помощник для вызова функций с общим HTTP‑клиентом,
позволяя переиспользовать один клиент для нескольких запросов.
"""

import typing
from app.http_client import get_http_client

T = typing.TypeVar("T")


async def perform_request(
        func: typing.Callable[..., typing.Awaitable[T]],
        *args: typing.Any,
        client=None,
        **kwargs: typing.Any,
) -> T:
    """Выполнить *func* с общим HTTP‑клиентом.

    Если *client* не передан, используется :func:`get_http_client`.
    Прочие позиционные и именованные аргументы пробрасываются в *func*.
    """
    if client is None:
        client = get_http_client()
    return await func(*args, client=client, **kwargs)
