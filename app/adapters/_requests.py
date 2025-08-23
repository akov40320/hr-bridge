import httpx
from typing import Any, Callable, Optional, Type

from app.core.retry import with_retry


def _is_retryable(status: int) -> bool:
    return status == 429 or 500 <= status < 600


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    json: Any = None,
    timeout: int = 30,
    attempts: int = 5,
    error_cls: Type[Exception],
    service: str,
    action: str,
    retry_func: Callable = with_retry,
) -> httpx.Response:
    async def attempt() -> httpx.Response:
        r = await client.request(
            method,
            url,
            headers=headers,
            json=json,
            timeout=timeout,
        )
        r.raise_for_status()
        return r

    try:
        return await retry_func(
            attempt,
            attempts=attempts,
            is_retryable=lambda e: isinstance(e, httpx.HTTPStatusError) and _is_retryable(e.response.status_code),
        )
    except httpx.HTTPStatusError as e:  # pragma: no cover - network errors
        raise error_cls(f"{service} {action} failed {e.response.status_code}: {e.response.text}") from e
