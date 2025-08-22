import httpx
from typing import Optional

from app.core.config import settings
from app.api.oauth2 import ensure_fresh_access
from app.core.retry import with_retry


class AvitoError(Exception): ...


def _is_retryable(status: int) -> bool:
    return status == 429 or 500 <= status < 600


async def _access_token(owner_id: Optional[str], client: httpx.AsyncClient) -> str:
    return await ensure_fresh_access(
        service="avito",
        token_url=settings.AVITO_TOKEN_URL,
        client_id=settings.AVITO_CLIENT_ID,
        client_secret=settings.AVITO_CLIENT_SECRET,
        redirect_uri=settings.AVITO_REDIRECT_URI,
        use_basic_auth=True,
        owner_id=owner_id,
        http_client=client,
    )


async def send_message(
    negotiation_id: str,
    text: str,
    owner_id: Optional[str],
    client: httpx.AsyncClient,
) -> None:
    access = await _access_token(owner_id, client)
    url = settings.AVITO_API_BASE.rstrip("/") + settings.AVITO_SEND_MESSAGE_PATH.format(negotiation_id=negotiation_id)
    body = {"message": {"text": text}}

    async def attempt() -> None:
        r = await client.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {access}",
                "Accept": "application/json",
            },
            timeout=30,
        )
        r.raise_for_status()

    try:
        await with_retry(
            attempt,
            attempts=5,
            is_retryable=lambda e: isinstance(e, httpx.HTTPStatusError) and _is_retryable(e.response.status_code),
        )
    except httpx.HTTPStatusError as e:  # pragma: no cover - network errors
        raise AvitoError(f"Avito send_message failed {e.response.status_code}: {e.response.text}") from e


async def mark_read(
    negotiation_id: str,
    owner_id: Optional[str],
    client: httpx.AsyncClient,
) -> None:
    access = await _access_token(owner_id, client)
    url = settings.AVITO_API_BASE.rstrip("/") + settings.AVITO_MARK_READ_PATH.format(negotiation_id=negotiation_id)

    async def attempt() -> None:
        r = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {access}",
                "Accept": "application/json",
            },
            timeout=20,
        )
        r.raise_for_status()

    try:
        await with_retry(
            attempt,
            attempts=5,
            is_retryable=lambda e: isinstance(e, httpx.HTTPStatusError) and _is_retryable(e.response.status_code),
        )
    except httpx.HTTPStatusError as e:  # pragma: no cover - network errors
        raise AvitoError(f"Avito mark_read failed {e.response.status_code}: {e.response.text}") from e
