"""Вспомогательные функции для HTTP‑запросов с автоматическими повторами."""

from typing import Any, Callable, Optional, Type

import httpx

from app.core.retry import with_retry


def _is_retryable(status: int) -> bool:
    """Возвращает ``True``, если код статуса означает ошибку, которую можно повторить."""
    return status == 429 or 500 <= status < 600


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    json: Any = None,
    timeout: int = 30,
    data: Any = None,
    attempts: int = 5,
    error_cls: Type[Exception],
    service: str,
    action: str,
    retry_func: Callable = with_retry,
) -> httpx.Response:
    """Выполняет HTTP‑запрос и повторяет его при временных сбоях."""
    # pylint: disable=too-many-arguments

    async def attempt() -> httpx.Response:
        r = await client.request(
            method,
            url,
            headers=headers,
            json=json,
            data=data,
            timeout=timeout,
        )
        r.raise_for_status()
        return r

    try:
        return await retry_func(
            attempt,
            attempts=attempts,
            is_retryable=lambda e: (
                isinstance(e, httpx.HTTPStatusError)
                and _is_retryable(e.response.status_code)
            ),
        )
    except httpx.HTTPStatusError as e:  # pragma: no cover - сетевые ошибки
        raise error_cls(
            f"{service} {action}: ошибка {e.response.status_code}: {e.response.text}"
        ) from e
