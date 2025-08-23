"""Utilities for refreshing OAuth2 tokens and ensuring valid access tokens."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.db.token_store import DbTokenStore, TokenData
from app.http_client import get_http_client


class OAuth2RefreshError(Exception):
    """Raised when the OAuth2 refresh flow fails."""


@dataclass
class OAuth2Config:
    """Configuration required for OAuth2 token refreshes."""

    service: str
    token_url: str
    client_id: str
    client_secret: str
    redirect_uri: Optional[str] = None
    use_basic_auth: bool = False
    owner_id: Optional[str] = None


async def refresh_tokens(
    *,
    config: OAuth2Config,
    refresh_token: str,
    http_client: httpx.AsyncClient | None = None,
) -> TokenData:
    """Refresh OAuth2 tokens using the provided configuration."""

    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    auth = (
        httpx.BasicAuth(config.client_id, config.client_secret)
        if config.use_basic_auth
        else None
    )
    if not config.use_basic_auth:
        data["client_id"] = config.client_id
        data["client_secret"] = config.client_secret
    if config.redirect_uri:
        data["redirect_uri"] = config.redirect_uri

    client = http_client or get_http_client()
    r = await client.post(
        config.token_url,
        data=data,
        headers={"Accept": "application/json"},
        auth=auth,
        timeout=30,
    )
    if r.status_code >= 400:
        raise OAuth2RefreshError(
            f"{config.service} refresh failed {r.status_code}: {r.text}"
        )

    d = r.json()
    server_time = int(d.get("server_time", time.time()))
    expires_in = int(d.get("expires_in", 3600))

    res: TokenData = {
        "access_token": d["access_token"],
        "refresh_token": d.get("refresh_token", refresh_token),
        "expires_at": server_time + expires_in - 120,
    }
    await DbTokenStore(config.service, config.owner_id).save(res)
    return res


async def ensure_fresh_access(
    *,
    config: OAuth2Config,
    margin_sec: int = 120,
    http_client: httpx.AsyncClient | None = None,
) -> str:
    """Return a valid access token, refreshing it when necessary."""

    store = DbTokenStore(config.service, config.owner_id)
    data = await store.load()
    now = time.time()
    if now > data["expires_at"] - margin_sec:
        data = await refresh_tokens(
            config=config,
            refresh_token=data["refresh_token"],
            http_client=http_client,
        )
    return data["access_token"]
