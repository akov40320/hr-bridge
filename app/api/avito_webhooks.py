"""Utilities to ensure Avito webhooks are configured and up-to-date."""
# pylint: disable=line-too-long, broad-exception-caught

from __future__ import annotations
import logging
from typing import Any

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.api.oauth2 import ensure_fresh_access
from app.db.token_store import DbTokenStore
from app.core.config import get_settings
from app.core.oauth_helpers import avito_config

log = logging.getLogger(__name__)

API_BASE = "https://api.avito.ru"


def _canon(u: str) -> str:
    return (u or "").strip().rstrip("/")


def _target_url() -> str:
    s = get_settings()
    return (getattr(s, "AVITO_WEBHOOK_URL", "") or "").strip()


def _events() -> list[str]:
    """
    Список событий для мессенджера из ENV AVITO_MESSENGER_EVENTS
    (по умолчанию только 'message').
    """
    s = get_settings()
    raw = (getattr(s, "AVITO_MESSENGER_EVENTS", "") or "").strip()
    return [t.strip() for t in raw.split(",") if t.strip()] or ["message"]


def _secret() -> str | None:
    s = get_settings()
    v = (getattr(s, "AVITO_WEBHOOK_SECRET", "") or "").strip()
    return v or None


async def _auth_headers(owner_id: str, client: httpx.AsyncClient) -> dict[str, str]:
    """Build Authorization headers using a fresh Avito access token."""
    access = await ensure_fresh_access(config=avito_config(owner_id), http_client=client)
    return {
        "Authorization": f"Bearer {access}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "hr-bridge/1.0 (+https://hr-bridge.onrender.com)",
    }


# -------------------- Messenger --------------------

_MESSENGER_GET_CANDIDATES = [
    "/messenger/v3/webhook",
    "/messenger/v2/webhook",  # на всякий случай, если у кого-то старая версия
]
_MESSENGER_POST = "/messenger/v3/webhook"


async def _get_messenger_webhook(client, headers):
    for path in _MESSENGER_GET_CANDIDATES:
        try:
            r = await client.get(f"{API_BASE}{path}", headers=headers, timeout=20)
            if r.status_code == 404:
                log.info("avito: messenger get %s -> 404", path)
                continue
            log.info("avito: messenger get %s -> %s", path, r.status_code)
            r.raise_for_status()
            js = r.json()
            log.debug("avito: messenger current: %s", js)
            return js
        except httpx.HTTPStatusError as e:
            log.warning("avito: messenger get %s failed: %s %s", path, e.response.status_code, e.response.text[:200])
            continue
    return None


async def _upsert_messenger_webhook(client: httpx.AsyncClient, headers: dict[str, str], url: str, events: list[str],
                                    secret: str | None):
    body: dict[str, Any] = {"url": url, "events": events}
    if secret:
        body["secret"] = secret
    log.info("avito: messenger upsert %s events=%s", _MESSENGER_POST, ",".join(events))
    r = await client.post(f"{API_BASE}{_MESSENGER_POST}", headers=headers, json=body, timeout=20)
    log.info("avito: messenger upsert resp=%s body=%s", r.status_code, (r.text[:200] if r.text else ""))
    r.raise_for_status()
    return r.json()


# -------------------- Job / Applications --------------------

# На разных ревизиях доки встречается singular/plural — сделаем авто-детект.
_APPLICATIONS_GET_CANDIDATES = [
    "/job/v1/applications/webhooks",
    "/job/v1/applications/webhook",
]
# Обычно POST туда же:
_APPLICATIONS_POST_CANDIDATES = [
    "/job/v1/applications/webhooks",
    "/job/v1/applications/webhook",
]


async def _get_applications_webhook(client: httpx.AsyncClient, headers: dict[str, str]) -> tuple[str, dict] | tuple[
    None, None]:
    for path in _APPLICATIONS_GET_CANDIDATES:
        try:
            r = await client.get(f"{API_BASE}{path}", headers=headers, timeout=20)
            if r.status_code == 404:
                log.info("avito: applications get %s -> 404", path)
                continue
            log.info("avito: applications get %s -> %s", path, r.status_code)
            r.raise_for_status()
            js = r.json()
            log.debug("avito: applications current: %s", js)
            return (path, js)
        except httpx.HTTPStatusError as e:
            log.warning("avito: applications get %s failed: %s %s", path, e.response.status_code, e.response.text[:200])
            continue
    return (None, None)


async def _upsert_applications_webhook(client: httpx.AsyncClient, headers: dict[str, str], post_path: str, url: str,
                                       secret: str | None):
    body: dict[str, Any] = {"url": url}
    if secret:
        body["secret"] = secret
    log.info("avito: applications upsert %s", post_path)
    r = await client.post(f"{API_BASE}{post_path}", headers=headers, json=body, timeout=20)
    log.info("avito: applications upsert resp=%s body=%s", r.status_code, (r.text[:200] if r.text else ""))
    r.raise_for_status()
    return r.json()


# -------------------- Public entry --------------------

async def ensure_avito_webhooks(client: httpx.AsyncClient) -> None:  # pylint: disable=too-many-branches
    """
    Идемпотентная регистрация Avito webhooks для всех известных владельцев.
    — Messenger: /messenger/v3/webhook
    — Job/Applications: /job/v1/applications/webhook(s)
    """
    url = _target_url()
    if not url:
        log.info("Avito webhook: AVITO_WEBHOOK_URL пуст — пропускаю регистрацию")
        return

    events = _events()
    secret = _secret()

    try:
        owners = await DbTokenStore.list_owners("avito")
        if not owners:
            raise RuntimeError("нет владельцев Avito")
    except (RuntimeError, SQLAlchemyError):
        log.info("Avito webhook: нет токенов владельцев — пропускаю регистрацию")
        return

    for owner_id in owners:
        try:
            headers = await _auth_headers(owner_id, client)
        except Exception:
            log.info("Avito webhook: не удалось получить access_token для owner=%s — пропускаю", owner_id)
            continue

        # --- Messenger
        try:
            current = await _get_messenger_webhook(client, headers)
            need_update = True
            if isinstance(current, dict):
                cur_url = _canon(str(current.get("url", "")))
                cur_events = sorted([str(x) for x in (current.get("events") or [])])
                need_update = not (_canon(url) == cur_url and sorted(events) == cur_events)
            if need_update:
                await _upsert_messenger_webhook(client, headers, url, events, secret)
                log.info("Avito messenger webhook: настроено -> %s [%s]", url, ",".join(events))
            else:
                log.info("Avito messenger webhook: уже настроено -> %s [%s]", url, ",".join(events))
        except httpx.HTTPError as e:
            log.exception("Avito messenger webhook: ошибка регистрации: %s", e)

        # --- Applications
        try:
            get_path, conf = await _get_applications_webhook(client, headers)
            post_path = get_path or _APPLICATIONS_POST_CANDIDATES[0]
            need_update = True
            if isinstance(conf, dict):
                cur_url = _canon(str(conf.get("url", ""))) if "url" in conf else _canon(
                    str(conf.get("callback_url", "")))
                if cur_url:
                    need_update = _canon(url) != cur_url
            if need_update:
                await _upsert_applications_webhook(client, headers, post_path, url, secret)
                log.info("Avito applications webhook: настроено -> %s", url)
            else:
                log.info("Avito applications webhook: уже настроено -> %s", url)
        except httpx.HTTPError as e:
            log.exception("Avito applications webhook: ошибка регистрации: %s", e)





