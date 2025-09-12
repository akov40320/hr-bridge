"""Обеспечивает корректную и идемпотентную регистрацию вебхуков HH."""

from __future__ import annotations
# pylint: disable=line-too-long, too-many-nested-blocks

import logging
import json
import re
from typing import Any

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.api.oauth2 import OAuth2Config
from app.core.oauth_helpers import hh_access
from app.db.token_store import DbTokenStore
from app.core.config import get_settings

log = logging.getLogger(__name__)

HH_SUBS_URL = "https://api.hh.ru/webhook/subscriptions"


def _norm(s: str) -> str:
    """Нормализация названий событий: '.', '-', пробелы -> '_', lower."""
    return re.sub(r"[.\-\s]+", "_", s.strip().lower())


# Поддерживаемые события (ключи — НОРМАЛИЗОВАННЫЕ)
EVENT_MAP: dict[str, str] = {
    "negotiation_created": "NEW_NEGOTIATION_VACANCY",
    "negotiation_status_changed": "NEGOTIATION_EMPLOYER_STATE_CHANGE",
    # Если в дальнейшем понадобятся сообщения — добавьте сюда:
    # "message_created": "NEW_NEGOTIATION_MESSAGE",
}


def _target_url() -> str:
    s = get_settings()
    return (getattr(s, "HH_WEBHOOK_URL", "") or "").strip()


def _canon(u: str) -> str:
    """Канонизация URL для сравнения."""
    return (u or "").strip().rstrip("/")


def _keyify_action(x: dict) -> tuple:
    """Ключ для сравнения action (тип + settings)."""
    return (x.get("type"), tuple(sorted((x.get("settings") or {}).items())))


def _same_actions(a_list: list[dict], b_list: list[dict]) -> bool:
    """Равенство множеств actions без учёта порядка."""
    return set(map(_keyify_action, a_list)) == set(map(_keyify_action, b_list))


def _actions() -> list[dict]:
    """Собирает actions из ENV HH_WEBHOOK_EVENTS."""
    s = get_settings()
    raw = (getattr(s, "HH_WEBHOOK_EVENTS", "") or "").strip()
    tokens = [t for t in (x.strip() for x in raw.split(",")) if t] or ["negotiation.created"]

    actions: list[dict] = []
    invalid: list[str] = []

    for token in tokens:
        key = _norm(token)
        type_name = EVENT_MAP.get(key)
        if not type_name:
            invalid.append(token)
            continue
        if type_name == "NEW_NEGOTIATION_VACANCY":
            actions.append({"type": type_name, "settings": {"vacancies_only_mine": False}})
        else:
            actions.append({"type": type_name})

    if invalid:
        log.warning("HH webhook: проигнорированы неподдерживаемые события: %s", ",".join(invalid))
    return actions


async def _list_all_subs(client: httpx.AsyncClient, headers: dict[str, str]) -> list[dict]:
    """Возвращает все подписки с учётом пагинации (если она есть)."""
    subs: list[dict] = []
    page = 0
    per_page = 100
    while True:
        r = await client.get(
            HH_SUBS_URL,
            headers=headers,
            params={"page": page, "per_page": per_page},
            timeout=20,
        )
        r.raise_for_status()
        js: Any = r.json()
        items = js if isinstance(js, list) else js.get("items", [])
        subs.extend(items)
        if isinstance(js, list):
            break
        pages = js.get("pages")
        if not isinstance(pages, int) or page + 1 >= pages:
            break
        page += 1
    return subs


async def _find_sub_by_url(client: httpx.AsyncClient, headers: dict[str, str], url: str) -> dict | None:
    """Ищет подписку по точному URL (с канонизацией)."""
    cu = _canon(url)
    for it in await _list_all_subs(client, headers):
        if _canon(str(it.get("url", ""))) == cu:
            return it
    return None


async def ensure_hh_webhook(client: httpx.AsyncClient) -> None:  # pylint: disable=too-many-branches,too-many-locals,too-many-statements,too-many-nested-blocks
    """Создать/обновить подписку HH, идемпотентно (POST/PUT/DELETE при необходимости)."""
    base_url = _target_url()
    if not base_url:
        log.info("HH webhook: HH_WEBHOOK_URL пуст — пропускаю регистрацию")
        return

    try:
        owners = await DbTokenStore.list_owners("hh")
        if not owners:
            raise RuntimeError("нет работодателей")
    except (RuntimeError, SQLAlchemyError):
        log.info("HH webhook: нет токена работодателя — пропускаю регистрацию")
        return

    desired = _actions()
    if not desired:
        log.warning("HH webhook: нет валидных событий — пропускаю регистрацию")
        return

    s = get_settings()
    for employer_id in owners:
        url = f"{base_url.rstrip('/')}/{employer_id}"
        try:
            access = await hh_access(client, employer_id)
        except (RuntimeError, SQLAlchemyError):
            continue

        headers = {
            "Authorization": f"Bearer {access}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "HH-User-Agent": "hr-bridge/1.0 (+https://hr-bridge.onrender.com; ops@hr-bridge.onrender.com)",
        }

        try:
            # 1) ищем подписку с нашим URL среди всех страниц
            current = await _find_sub_by_url(client, headers, url)

            # 2) если нет — пробуем создать
            if current is None:
                cr = await client.post(HH_SUBS_URL, json={"url": url, "actions": desired}, headers=headers, timeout=20)
                if cr.status_code == 400:
                    # 2a) если "already_exist" — в аккаунте уже есть подписка, нужно обновить существующую
                    try:
                        err = cr.json()
                    except (ValueError, json.JSONDecodeError):
                        err = {}
                    if any(e.get("value") == "already_exist" for e in err.get("errors", [])):
                        log.info("HH webhook: подписка уже существует — пробую обновить существующую")
                        # Берём любую существующую подписку и пробуем заменить url+actions через PUT,
                        # если нельзя — удаляем и создаём заново.
                        all_subs = await _list_all_subs(client, headers)
                        if not all_subs:
                            log.warning("HH webhook: already_exist, но список подписок пуст — проверь права")
                            continue
                        victim = all_subs[0]
                        sub_id = victim.get("id") or victim.get("subscription_id")
                        if not sub_id:
                            log.warning("HH webhook: не удалось определить id существующей подписки")
                            continue
                        # Пытаемся PUT url+actions
                        pu = await client.put(
                            f"{HH_SUBS_URL}/{sub_id}",
                            json={"url": url, "actions": desired},
                            headers=headers,
                            timeout=20,
                        )
                        if pu.status_code in (400, 422):
                            # Если нельзя менять url — удаляем и создаём заново
                            await client.delete(f"{HH_SUBS_URL}/{sub_id}", headers=headers, timeout=20)
                            cr2 = await client.post(
                                HH_SUBS_URL, json={"url": url, "actions": desired}, headers=headers, timeout=20
                            )
                            cr2.raise_for_status()
                            log.info("HH webhook: заменено удалением -> %s [%s]", url, ",".join(a["type"] for a in desired))
                        else:
                            pu.raise_for_status()
                            log.info("HH webhook: обновлено (PUT) -> %s [%s]", url, ",".join(a["type"] for a in desired))
                        return
                    cr.raise_for_status()
                else:
                    cr.raise_for_status()
                    log.info("HH webhook: создано -> %s [%s]", url, ",".join(a["type"] for a in desired))
                    return

            # 3) если подписка с нашим URL уже есть — сверяем actions и обновляем при необходимости
            curr_actions = current.get("actions", [])
            if not _same_actions(curr_actions, desired):
                sub_id = current.get("id") or current.get("subscription_id")
                if not sub_id:
                    log.warning("HH webhook: не удалось определить id подписки для обновления")
                    continue
                pu = await client.put(
                    f"{HH_SUBS_URL}/{sub_id}",
                    json={"actions": desired},
                    headers=headers,
                    timeout=20,
                )
                pu.raise_for_status()
                log.info("HH webhook: обновлено -> %s [%s]", url, ",".join(a["type"] for a in desired))
            else:
                log.info("HH webhook: уже настроено -> %s [%s]", url, ",".join(a["type"] for a in desired))
            return

        except httpx.HTTPStatusError as e:
            log.exception("HH webhook: HTTP ошибка (%s): %s", e.response.status_code, e.response.text)
        except (httpx.HTTPError, ValueError) as e:
            log.exception("HH webhook: непредвиденная ошибка: %s", e)

    log.info("HH webhook: подходящая подписка не найдена/не создана для известных владельцев — проверь токены/права")
