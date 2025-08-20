from __future__ import annotations
import time
import httpx
from typing import Optional
from app.token_store import DbTokenStore, TokenData


class OAuth2RefreshError(Exception):
    pass


async def refresh_tokens(
    *,
    service: str,
    token_url: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    redirect_uri: Optional[str] = None,
    use_basic_auth: bool = False,
    owner_id: Optional[str] = None,
) -> TokenData:
    """
    Универсальный refresh_token.
    HH — client_id/secret в теле; Avito — BasicAuth.
    """
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    auth = httpx.BasicAuth(client_id, client_secret) if use_basic_auth else None
    if not use_basic_auth:
        data["client_id"] = client_id
        data["client_secret"] = client_secret
    if redirect_uri:
        data["redirect_uri"] = redirect_uri

    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post(token_url, data=data, headers={"Accept": "application/json"}, auth=auth)
    if r.status_code >= 400:
        raise OAuth2RefreshError(f"{service} refresh failed {r.status_code}: {r.text}")

    d = r.json()
    server_time = int(d.get("server_time", time.time()))
    expires_in = int(d.get("expires_in", 3600))

    res: TokenData = {
        "access_token": d["access_token"],
        "refresh_token": d.get("refresh_token", refresh_token),
        "expires_at": server_time + expires_in - 120,
    }
    await DbTokenStore(service, owner_id).save(res)
    return res


async def ensure_fresh_access(
    *,
    service: str,
    token_url: str,
    client_id: str,
    client_secret: str,
    redirect_uri: Optional[str] = None,
    use_basic_auth: bool = False,
    margin_sec: int = 120,
    owner_id: Optional[str] = None,
) -> str:
    """
    Возвращает свежий access_token, обновляя при необходимости.
    """
    store = DbTokenStore(service, owner_id)
    data = await store.load()
    now = time.time()
    if now > data["expires_at"] - margin_sec:
        data = await refresh_tokens(
            service=service,
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=data["refresh_token"],
            redirect_uri=redirect_uri,
            use_basic_auth=use_basic_auth,
            owner_id=owner_id,
        )
    return data["access_token"]
