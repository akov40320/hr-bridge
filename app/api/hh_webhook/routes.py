from __future__ import annotations

import logging

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.api.oauth2 import OAuth2Config, ensure_fresh_access
from app.db.token_store import DbTokenStore
from app.core.config import get_settings

from . import client as wh_client, subscription as wh_sub

log = logging.getLogger(__name__)


async def ensure_hh_webhook(client: httpx.AsyncClient) -> None:
    """Создать/обновить подписку HH, идемпотентно (POST/PUT/DELETE при необходимости)."""
    url_base = wh_sub._target_url()
    if not url_base:
        log.info("HH webhook: HH_WEBHOOK_URL пуст — пропускаю регистрацию")
        return
    url_base = url_base.rstrip("/")

    try:
        owners = await DbTokenStore.list_owners("hh")
        if not owners:
            raise RuntimeError("нет работодателей")
    except (RuntimeError, SQLAlchemyError):
        log.info("HH webhook: нет токена работодателя — пропускаю регистрацию")
        return

    desired = wh_sub._actions()
    if not desired:
        log.warning("HH webhook: нет валидных событий — пропускаю регистрацию")
        return

    s = get_settings()
    for employer_id in owners:
        url = f"{url_base}/{employer_id}"
        try:
            access = await ensure_fresh_access(
                config=OAuth2Config(
                    service="hh",
                    token_url=s.HH_TOKEN_URL,
                    client_id=s.HH_CLIENT_ID,
                    client_secret=s.HH_CLIENT_SECRET.get_secret_value(),
                    redirect_uri=s.HH_REDIRECT_URI,
                    use_basic_auth=False,
                    owner_id=employer_id,
                ),
                http_client=client,
            )
        except (RuntimeError, SQLAlchemyError):
            continue

        user_agent = getattr(s, "HH_USER_AGENT", None) or "hr-bridge/1.0 (+https://hr-bridge.onrender.com)"
        headers = {
            "Authorization": f"Bearer {access}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        }

        try:
            current = await wh_client._find_sub_by_url(client, headers, url)

            if current is None:
                cr = await client.post(
                    wh_client.HH_SUBS_URL, json={"url": url, "actions": desired}, headers=headers, timeout=20
                )
                if cr.status_code == 400:
                    try:
                        err = cr.json()
                    except Exception:  # noqa: BLE001
                        err = {}
                    if any(e.get("value") == "already_exist" for e in err.get("errors", [])):
                        log.info("HH webhook: подписка уже существует — пробую обновить существующую")
                        all_subs = await wh_client._list_all_subs(client, headers)
                        if not all_subs:
                            log.warning("HH webhook: already_exist, но список подписок пуст — проверь права")
                            continue
                        victim = all_subs[0]
                        sub_id = victim.get("id") or victim.get("subscription_id")
                        if not sub_id:
                            log.warning("HH webhook: не удалось определить id существующей подписки")
                            continue
                        pu = await client.put(
                            f"{wh_client.HH_SUBS_URL}/{sub_id}",
                            json={"url": url, "actions": desired},
                            headers=headers,
                            timeout=20,
                        )
                        if pu.status_code in (400, 422):
                            await client.delete(
                                f"{wh_client.HH_SUBS_URL}/{sub_id}", headers=headers, timeout=20
                            )
                            cr2 = await client.post(
                                wh_client.HH_SUBS_URL,
                                json={"url": url, "actions": desired},
                                headers=headers,
                                timeout=20,
                            )
                            cr2.raise_for_status()
                            log.info(
                                "HH webhook: заменено удалением -> %s [%s]",
                                url,
                                ",".join(a["type"] for a in desired),
                            )
                        else:
                            pu.raise_for_status()
                            log.info(
                                "HH webhook: обновлено (PUT) -> %s [%s]",
                                url,
                                ",".join(a["type"] for a in desired),
                            )
                        return
                    cr.raise_for_status()
                else:
                    cr.raise_for_status()
                    log.info(
                        "HH webhook: создано -> %s [%s]",
                        url,
                        ",".join(a["type"] for a in desired),
                    )
                    return

            curr_actions = current.get("actions", [])
            if not wh_sub._same_actions(curr_actions, desired):
                sub_id = current.get("id") or current.get("subscription_id")
                if not sub_id:
                    log.warning("HH webhook: не удалось определить id подписки для обновления")
                    continue
                pu = await client.put(
                    f"{wh_client.HH_SUBS_URL}/{sub_id}",
                    json={"actions": desired},
                    headers=headers,
                    timeout=20,
                )
                pu.raise_for_status()
                log.info(
                    "HH webhook: обновлено -> %s [%s]",
                    url,
                    ",".join(a["type"] for a in desired),
                )
            else:
                log.info(
                    "HH webhook: уже настроено -> %s [%s]",
                    url,
                    ",".join(a["type"] for a in desired),
                )
            return

        except httpx.HTTPStatusError as e:
            log.exception(
                "HH webhook: HTTP ошибка (%s): %s", e.response.status_code, e.response.text
            )
        except (httpx.HTTPError, ValueError) as e:
            log.exception("HH webhook: непредвиденная ошибка: %s", e)

    log.info(
        "HH webhook: подходящая подписка не найдена/не создана для известных владельцев — проверь токены/права"
    )
