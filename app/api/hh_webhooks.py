"""Обеспечивает корректную регистрацию вебхуков HH (идемпотентно)."""

import logging
import re
import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.db.token_store import DbTokenStore
from app.core.config import get_settings

log = logging.getLogger(__name__)

HH_SUBS_URL = "https://api.hh.ru/webhook/subscriptions"

# Нормализатор названий событий из ENV: ".", "-", пробелы -> "_", lower
def _norm(s: str) -> str:
    return re.sub(r"[.\-\s]+", "_", s.strip().lower())

# Поддерживаемые события (ключи — НОРМАЛИЗОВАННЫЕ):
# По докам HH доступны события по переговорам; сообщения через webhooks не гарантируются.
EVENT_MAP = {
    "negotiation_created": "NEW_NEGOTIATION_VACANCY",
    "negotiation_status_changed": "NEGOTIATION_EMPLOYER_STATE_CHANGE",
    # "message_created": "NEW_NEGOTIATION_MESSAGE",  # если включишь — проверь в доках/кабинете
}

def _target_url() -> str:
    s = get_settings()
    return (getattr(s, "HH_WEBHOOK_URL", "") or "").strip()

def _actions() -> list[dict]:
    """
    Собирает actions из ENV HH_WEBHOOK_EVENTS.
    Пример ENV: HH_WEBHOOK_EVENTS=negotiation.created,negotiation.status_changed
    """
    s = get_settings()
    raw = (getattr(s, "HH_WEBHOOK_EVENTS", "") or "").strip()
    tokens = [t for t in (x.strip() for x in raw.split(",")) if t] or ["negotiation.created"]

    actions, invalid = [], []
    for token in tokens:
        key = _norm(token)
        type_name = EVENT_MAP.get(key)
        if not type_name:
            invalid.append(token)
            continue
        # Для NEW_NEGOTIATION_VACANCY допустима настройка фильтра вакансий
        if type_name == "NEW_NEGOTIATION_VACANCY":
            actions.append({"type": type_name, "settings": {"vacancies_only_mine": False}})
        else:
            actions.append({"type": type_name})

    if invalid:
        log.warning("HH webhook: проигнорированы неподдерживаемые события: %s", ",".join(invalid))
    return actions

def _same_action(a: dict, b: dict) -> bool:
    """Сравнение action по типу и настройкам (а не только по типу)."""
    return a.get("type") == b.get("type") and (a.get("settings") or {}) == (b.get("settings") or {})

async def ensure_hh_webhook(client: httpx.AsyncClient) -> None:
    """Создать/обновить подписку HH, идемпотентно."""
    url = _target_url()
    if not url:
        log.info("HH webhook: HH_WEBHOOK_URL пуст — пропускаю регистрацию")
        return

    # 1) токен работодателя
    try:
        owners = await DbTokenStore.list_owners("hh")
        employer_id = owners[0] if owners else None
        if not employer_id:
            raise RuntimeError("нет работодателей")
        tok = await DbTokenStore("hh", employer_id).load()
    except (RuntimeError, SQLAlchemyError):
        log.info("HH webhook: нет токена работодателя — пропускаю регистрацию")
        return

    headers = {
        "Authorization": f"Bearer {tok['access_token']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "HH-User-Agent": "hr-bridge/1.0 (+https://hr-bridge.onrender.com; ops@hr-bridge.onrender.com)",
    }

    desired = _actions()
    if not desired:
        log.warning("HH webhook: нет валидных событий — пропускаю регистрацию")
        return

    # 2) читаем текущие подписки и ищем по URL (без учёта завершающего слэша)
    def _canon(u: str) -> str:
        return u.rstrip("/").strip()

    try:
        r = await client.get(HH_SUBS_URL, headers=headers, timeout=20)
        if r.status_code in (401, 403, 404):
            log.warning("HH webhook: %s — нет прав/токен/фича недоступна", r.status_code)
            return
        r.raise_for_status()
        js = r.json()
        items = js if isinstance(js, list) else js.get("items", [])
        current = next((it for it in items if _canon(str(it.get("url", ""))) == _canon(url)), None)

        # helper: сравнить списки actions
        def _same_actions(a_list: list[dict], b_list: list[dict]) -> bool:
            if len(a_list) != len(b_list):
                return False
            # сравнение по множеству (тип+настройки)
            def keyify(x: dict) -> tuple:
                return (x.get("type"), tuple(sorted((x.get("settings") or {}).items())))
            return set(map(keyify, a_list)) == set(map(keyify, b_list))

        if current is None:
            # 3) создаём; если вернётся 400 already_exist — обрабатываем как "уже есть"
            cr = await client.post(HH_SUBS_URL, json={"url": url, "actions": desired}, headers=headers, timeout=20)
            if cr.status_code == 400:
                try:
                    err = cr.json()
                    if any(e.get("value") == "already_exist" for e in err.get("errors", [])):
                        log.info("HH webhook: подписка уже существует — пробую обновить")
                        # перечитываем и обновляем по URL
                        r2 = await client.get(HH_SUBS_URL, headers=headers, timeout=20)
                        r2.raise_for_status()
                        items2 = r2.json() if isinstance(r2.json(), list) else r2.json().get("items", [])
                        current = next((it for it in items2 if _canon(str(it.get("url", ""))) == _canon(url)), None)
                    else:
                        cr.raise_for_status()
                except Exception:  # noqa: BLE001
                    cr.raise_for_status()
            else:
                cr.raise_for_status()
                log.info("HH webhook: создано -> %s [%s]", url, ",".join(a["type"] for a in desired))
                return

        if current is None:
            # ничего не нашли даже после already_exist — считаем настроенным и выходим
            log.info("HH webhook: подписка существует (по ответу HH), но не найдена в списке — пропускаю")
            return

        # 4) обновляем, если конфигурации различаются (PUT вместо delete+post)
        curr_actions = current.get("actions", [])
        if not _same_actions(curr_actions, desired):
            sub_id = current.get("id") or current.get("subscription_id")
            if not sub_id:
                log.warning("HH webhook: не удалось определить id подписки для обновления")
                return
            pu = await client.put(f"{HH_SUBS_URL}/{sub_id}", json={"actions": desired}, headers=headers, timeout=20)
            pu.raise_for_status()
            log.info("HH webhook: обновлено -> %s [%s]", url, ",".join(a["type"] for a in desired))
        else:
            log.info("HH webhook: уже настроено -> %s [%s]", url, ",".join(a["type"] for a in desired))

    except httpx.HTTPStatusError as e:
        # полезно видеть request_id HH для тикетов
        body = e.response.text
        log.exception("HH webhook: HTTP ошибка (%s): %s", e.response.status_code, body)
    except (httpx.HTTPError, ValueError) as e:
        log.exception("HH webhook: непредвиденная ошибка: %s", e)
