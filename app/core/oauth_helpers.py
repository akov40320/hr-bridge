"""Small helpers to build OAuth2 configs and fetch fresh access tokens.

Centralizing this logic avoids duplication across modules.
"""

from __future__ import annotations

import httpx

from app.api.oauth2 import OAuth2Config, ensure_fresh_access
from app.core.config import get_settings


def hh_config(owner_id: str | None) -> OAuth2Config:
    s = get_settings()
    return OAuth2Config(
        service="hh",
        token_url=s.HH_TOKEN_URL,
        client_id=s.HH_CLIENT_ID,
        client_secret=s.HH_CLIENT_SECRET,
        redirect_uri=s.HH_REDIRECT_URI,
        use_basic_auth=False,
        owner_id=owner_id,
    )


def avito_config(owner_id: str | None) -> OAuth2Config:
    s = get_settings()
    return OAuth2Config(
        service="avito",
        token_url=s.AVITO_TOKEN_URL,
        client_id=s.AVITO_CLIENT_ID,
        client_secret=s.AVITO_CLIENT_SECRET,
        redirect_uri=s.AVITO_REDIRECT_URI,
        use_basic_auth=True,
        owner_id=owner_id,
    )


async def hh_access(http_client: httpx.AsyncClient, owner_id: str | None) -> str:
    """Return fresh HH access token for ``owner_id``."""
    return await ensure_fresh_access(config=hh_config(owner_id), http_client=http_client)


async def avito_access(http_client: httpx.AsyncClient, owner_id: str | None) -> str:
    """Return fresh Avito access token for ``owner_id``."""
    return await ensure_fresh_access(config=avito_config(owner_id), http_client=http_client)


__all__ = [
    "hh_config",
    "avito_config",
    "hh_access",
    "avito_access",
]

