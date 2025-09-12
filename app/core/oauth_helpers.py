"""Small helpers to build OAuth2 configs and fetch fresh access tokens.

Centralizing this logic avoids duplication and circular imports.
Imports from ``app.api.oauth2`` are performed lazily inside functions to
avoid importing the FastAPI router package during low-level adapter imports.
"""

from __future__ import annotations

import httpx
from app.core.config import get_settings


def hh_config(owner_id: str | None):  # -> OAuth2Config
    """Build HH OAuth2Config lazily to avoid import cycles."""
    # local import to avoid importing app.api at module import time
    from app.api.oauth2 import OAuth2Config  # pylint: disable=import-outside-toplevel

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


def avito_config(owner_id: str | None):  # -> OAuth2Config
    """Build Avito OAuth2Config lazily to avoid import cycles."""
    from app.api.oauth2 import OAuth2Config  # pylint: disable=import-outside-toplevel

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
    """Return fresh HH access token for ``owner_id`` (imports lazily)."""
    from app.api.oauth2 import ensure_fresh_access  # pylint: disable=import-outside-toplevel

    return await ensure_fresh_access(config=hh_config(owner_id), http_client=http_client)


async def avito_access(http_client: httpx.AsyncClient, owner_id: str | None) -> str:
    """Return fresh Avito access token for ``owner_id`` (imports lazily)."""
    from app.api.oauth2 import ensure_fresh_access  # pylint: disable=import-outside-toplevel

    return await ensure_fresh_access(config=avito_config(owner_id), http_client=http_client)


__all__ = [
    "hh_config",
    "avito_config",
    "hh_access",
    "avito_access",
]
