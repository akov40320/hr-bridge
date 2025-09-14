"""Утилиты для работы с Avito API."""

from typing import Optional

import httpx

from app.core.config import get_settings
from app.core.oauth_helpers import avito_config
from app.api.oauth2 import ensure_fresh_access
from app.core.retry import with_retry
from ._requests import request_with_retry


class AvitoError(Exception):
    """Исключение при ошибке взаимодействия с Avito API."""


async def _access_token(owner_id: Optional[str], client: httpx.AsyncClient) -> str:
    """Получить свежий access token для Avito API."""

    return await ensure_fresh_access(config=avito_config(owner_id), http_client=client)


async def send_message(
    negotiation_id: str,
    text: str,
    owner_id: Optional[str],
    client: httpx.AsyncClient,
) -> None:
    """Отправить текстовое сообщение в переписке Avito (negotiation)."""

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
    """Пометить сообщения в переписке Avito как прочитанные."""

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


async def list_items(
    *,
    owner_id: Optional[str],
    client: httpx.AsyncClient,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Fetch account ads (items) via Avito Core API.

    Uses the token bound to ``owner_id`` and path from settings
    (``AVITO_LIST_ITEMS_PATH``). Supports limit/offset pagination.
    Returns raw JSON from Avito.
    """

    s = get_settings()
    access = await _access_token(owner_id, client)

    base = s.AVITO_API_BASE.rstrip("/")
    path = getattr(s, "AVITO_LIST_ITEMS_PATH", "/core/v1/accounts/self/items")
    # Build URL with query parameters explicitly (request_with_retry lacks params)
    q = []
    if isinstance(limit, int) and limit > 0:
        q.append(f"limit={int(limit)}")
    if isinstance(offset, int) and offset >= 0:
        q.append(f"offset={int(offset)}")
    url = f"{base}{path}"
    if q:
        url = f"{url}?{'&'.join(q)}"

    r = await request_with_retry(
        client,
        "GET",
        url,
        headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/json",
        },
        timeout=20,
        error_cls=AvitoError,
        service="Avito",
        action="list_items",
        retry_func=with_retry,
    )

    return r.json() or {}
