"""Utilities for interacting with the Avito API."""

from typing import Optional

import httpx

from app.core.config import get_settings
from app.api.oauth2 import ensure_fresh_access, OAuth2Config
from app.core.retry import with_retry
from ._requests import request_with_retry


class AvitoError(Exception):
    """Error raised when Avito API communication fails."""


async def _access_token(owner_id: Optional[str], client: httpx.AsyncClient) -> str:
    """Retrieve a fresh access token for the Avito API."""

    s = get_settings()
    config = OAuth2Config(
        service="avito",
        token_url=s.AVITO_TOKEN_URL,
        client_id=s.AVITO_CLIENT_ID,
        client_secret=s.AVITO_CLIENT_SECRET.get_secret_value(),
        redirect_uri=s.AVITO_REDIRECT_URI,
        use_basic_auth=True,
        owner_id=owner_id,
    )
    return await ensure_fresh_access(config=config, http_client=client)


async def send_message(
    negotiation_id: str,
    text: str,
    owner_id: Optional[str],
    client: httpx.AsyncClient,
) -> None:
    """Send a text message in an Avito negotiation."""

    s = get_settings()
    access = await _access_token(owner_id, client)
    path = s.AVITO_SEND_MESSAGE_PATH.format(negotiation_id=negotiation_id)
    url = s.AVITO_API_BASE.rstrip("/") + path
    body = {"message": {"text": text}}

    await request_with_retry(
        client,
        "POST",
        url,
        json=body,
        headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/json",
        },
        timeout=30,
        error_cls=AvitoError,
        service="Avito",
        action="send_message",
        retry_func=with_retry,
    )


async def mark_read(
    negotiation_id: str,
    owner_id: Optional[str],
    client: httpx.AsyncClient,
) -> None:
    """Mark messages in an Avito negotiation as read."""

    s = get_settings()
    access = await _access_token(owner_id, client)
    path = s.AVITO_MARK_READ_PATH.format(negotiation_id=negotiation_id)
    url = s.AVITO_API_BASE.rstrip("/") + path

    await request_with_retry(
        client,
        "POST",
        url,
        headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/json",
        },
        timeout=20,
        error_cls=AvitoError,
        service="Avito",
        action="mark_read",
        retry_func=with_retry,
    )
