"""OAuth related endpoints."""

import logging
import re
import secrets
import time
from urllib.parse import urlencode

import httpx
from aio_pika import exceptions as aio_exc
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.services.queue import rabbitmq, RabbitMQClient
from app.db.token_store import DbTokenStore, TokenData
from app.http_client import get_http_client

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------- HH OAuth ----------
@router.get("/oauth/hh/start")
def hh_start(s=Depends(get_settings)):
    """Redirect to HeadHunter for OAuth authorization."""

    params = {
        "response_type": "code",
        "client_id": s.HH_CLIENT_ID,
        "redirect_uri": s.HH_REDIRECT_URI,
        "state": "hh1",
    }
    return RedirectResponse("https://hh.ru/oauth/authorize?" + urlencode(params))


@router.get("/oauth/hh/callback")
async def hh_callback(
    code: str | None = None,
    _state: str | None = None,
    http_client: httpx.AsyncClient = Depends(get_http_client),
    s=Depends(get_settings),
):
    """Handle HH OAuth callback and persist tokens."""

    if not code:
        return {"ok": False, "error": "no code"}

    error_response: dict[str, object] = {"ok": False, "provider": "hh"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": s.HH_CLIENT_ID,
        "client_secret": s.HH_CLIENT_SECRET.get_secret_value(),
        "redirect_uri": s.HH_REDIRECT_URI,
    }

    try:
        r = await http_client.post(
            s.HH_TOKEN_URL,
            data=data,
            headers={"Accept": "application/json"},
            timeout=30,
        )
    except httpx.HTTPError as e:
        error_response.update({"step": "token-exchange-exception", "error": str(e)})
    else:
        if r.status_code >= 400:
            error_response.update(
                {
                    "step": "token",
                    "status": r.status_code,
                    "body": r.text,
                }
            )
        else:
            d = r.json()
            try:
                me = await http_client.get(
                    "https://api.hh.ru/me",
                    headers={"Authorization": f"Bearer {d['access_token']}"},
                    timeout=15,
                )
                me.raise_for_status()
                employer_id = str(me.json().get("employer", {}).get("id") or "")
            except httpx.HTTPError as e:
                error_response.update({"step": "me", "error": str(e)})
            else:
                if not employer_id:
                    error_response.update({"step": "me", "error": "no employer.id"})
                else:
                    try:
                        expires_at = int(time.time()) + int(d.get("expires_in", 3600)) - 120
                        await DbTokenStore("hh", employer_id).save(
                            TokenData(
                                access_token=d["access_token"],
                                refresh_token=d.get("refresh_token", ""),
                                expires_at=expires_at,
                            )
                        )
                    except SQLAlchemyError as e:
                        error_response.update({"step": "save-token", "error": str(e)})
                    else:
                        return {"ok": True, "employer_id": employer_id}

    return error_response


# ---------- Avito OAuth ----------
@router.get("/oauth/avito/start")
def avito_start(s=Depends(get_settings)):
    """Redirect to Avito OAuth authorization endpoint."""

    if not (
        s.AVITO_CLIENT_ID
        and s.AVITO_REDIRECT_URI
        and s.AVITO_AUTHORIZE_URL
        and s.AVITO_TOKEN_URL
    ):
        return {"ok": False, "error": "avito env not set"}

    raw_scope = getattr(s, "AVITO_SCOPE", "") or ""
    scope = ",".join([s.strip() for s in re.split(r"[,\s]+", raw_scope) if s.strip()])

    state = secrets.token_urlsafe(16)  # CSRF
    params = {
        "response_type": "code",
        "client_id": s.AVITO_CLIENT_ID,
        "redirect_uri": s.AVITO_REDIRECT_URI,
        "state": state,
    }
    if scope:
        params["scope"] = scope

    return RedirectResponse(f"{s.AVITO_AUTHORIZE_URL}?{urlencode(params)}")


async def _exchange_avito_code(http_client: httpx.AsyncClient, s, code: str):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": s.AVITO_REDIRECT_URI,
    }
    auth = httpx.BasicAuth(
        s.AVITO_CLIENT_ID, s.AVITO_CLIENT_SECRET.get_secret_value()
    )
    try:
        r = await http_client.post(
            s.AVITO_TOKEN_URL,
            data=data,
            auth=auth,
            timeout=30,
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        return None, {
            "step": "token",
            "status": e.response.status_code,
            "body": e.response.text,
        }
    except httpx.HTTPError as e:  # pragma: no cover - network errors
        return None, {"step": "token-exchange-exception", "error": str(e)}

    tok = r.json()
    access = tok.get("access_token", "")
    if not access:
        return None, {"step": "token", "error": "no access_token"}
    return (tok, access), None


async def _fetch_avito_account(http_client: httpx.AsyncClient, access: str):
    try:
        me = await http_client.get(
            "https://api.avito.ru/core/v1/accounts/self",
            headers={
                "Authorization": f"Bearer {access}",
                "Accept": "application/json",
            },
            timeout=15,
        )
        me.raise_for_status()
    except httpx.HTTPStatusError as e:
        return None, {
            "step": "self",
            "status": e.response.status_code,
            "body": e.response.text,
        }
    except httpx.HTTPError as e:  # pragma: no cover - network errors
        return None, {"step": "self", "error": str(e)}

    account_id = str(me.json().get("id") or "")
    if not account_id:
        return None, {"step": "self", "error": "no account id"}
    return account_id, None


async def _save_avito_tokens(account_id: str, tok: dict, access: str):
    try:
        expires_at = int(time.time()) + int(tok.get("expires_in", 86400)) - 120
        await DbTokenStore("avito", account_id).save(
            TokenData(
                access_token=access,
                refresh_token=tok.get("refresh_token", ""),
                expires_at=expires_at,
            )
        )
    except SQLAlchemyError as e:
        return {"step": "save-token", "error": str(e)}
    return None


@router.get("/oauth/avito/callback")
async def avito_callback(
    code: str | None = None,
    _state: str | None = None,
    http_client: httpx.AsyncClient = Depends(get_http_client),
    s=Depends(get_settings),
):
    """Handle Avito OAuth callback and persist tokens."""

    if not code:
        return {"ok": False, "error": "no code"}
    if not (
        s.AVITO_TOKEN_URL
        and s.AVITO_CLIENT_ID
        and s.AVITO_CLIENT_SECRET.get_secret_value()
    ):
        return {"ok": False, "error": "avito token env not set"}

    token_result, error = await _exchange_avito_code(http_client, s, code)
    if error:
        return {"ok": False, "provider": "avito", **error}
    tok, access = token_result

    account_id, error = await _fetch_avito_account(http_client, access)
    if error:
        return {"ok": False, "provider": "avito", **error}

    error = await _save_avito_tokens(account_id, tok, access)
    if error:
        return {"ok": False, "provider": "avito", **error}

    return {"ok": True, "account_id": account_id}


# ---------- AmoCRM OAuth ----------
@router.get("/oauth/amo/start")
def amo_start(s=Depends(get_settings)):
    """Start amo OAuth flow and redirect to portal for authorization."""
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": s.AMO_CLIENT_ID,
        "redirect_uri": s.AMO_REDIRECT_URI,
        "response_type": "code",
        "state": state,
        "mode": "post_message",
    }
    return RedirectResponse("https://www.amocrm.ru/oauth?" + urlencode(params))


@router.get("/oauth/amo/callback")
async def amo_callback(
    code: str | None = None,
    _state: str | None = None,
    http_client: httpx.AsyncClient = Depends(get_http_client),
    queue_client: RabbitMQClient = Depends(lambda: rabbitmq),
    s=Depends(get_settings),
):
    """Process AmoCRM OAuth callback and store tokens."""

    if not code:
        return {"ok": False, "provider": "amo", "step": "callback", "error": "no code"}

    url = s.AMO_BASE_URL.rstrip("/") + "/oauth2/access_token"
    payload = {
        "client_id": s.AMO_CLIENT_ID,
        "client_secret": s.AMO_CLIENT_SECRET.get_secret_value(),
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": s.AMO_REDIRECT_URI,
    }

    try:
        r = await http_client.post(
            url,
            json=payload,
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if r.status_code >= 400:
            return {
                "ok": False,
                "provider": "amo",
                "step": "token",
                "status": r.status_code,
                "body": r.text,
            }
        d = r.json()
    except httpx.HTTPError as e:
        return {
            "ok": False,
            "provider": "amo",
            "step": "token-exchange-exception",
            "error": str(e),
        }

    try:
        server_time = int(d.get("server_time", time.time()))
        expires_in = int(d.get("expires_in", 3600))
        access = d["access_token"]
        refresh = d["refresh_token"]
        expires_at = server_time + expires_in - 120

        await DbTokenStore("amo").save(
            TokenData(
                access_token=access,
                refresh_token=refresh,
                expires_at=expires_at,
            )
        )

        try:
            await queue_client.publish_task({"platform": "system", "action": "hh_autofill", "payload": {}})
            logger.info("Queued hh_autofill after amo oauth")
        except aio_exc.AMQPError:
            logger.exception("Failed to queue hh_autofill after amo oauth")

    except SQLAlchemyError as e:
        return {
            "ok": False,
            "provider": "amo",
            "step": "save-token",
            "error": str(e),
        }

    return {"ok": True, "provider": "amo", "expires_in": expires_in}


__all__ = ["router"]
