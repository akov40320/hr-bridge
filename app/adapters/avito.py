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
