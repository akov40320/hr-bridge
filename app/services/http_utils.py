import httpx
from typing import Callable, Awaitable

from app.core.retry import with_retry


async def send_with_retry(
    client: httpx.AsyncClient,
    request_fn: Callable[[httpx.AsyncClient], Awaitable[httpx.Response]],
    is_retryable: Callable[[int], bool],
) -> httpx.Response:
    """Send HTTP request with retry on retryable status codes."""

    async def attempt() -> httpx.Response:
        resp = await request_fn(client)
        resp.raise_for_status()
        return resp

    return await with_retry(
        attempt,
        attempts=5,
        is_retryable=lambda exc: (
            isinstance(exc, httpx.HTTPStatusError)
            and is_retryable(exc.response.status_code)
        ),
    )
