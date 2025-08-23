"""Ensure HH webhook subscriptions are configured as expected."""

import logging
import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.db.token_store import DbTokenStore
from app.core.config import get_settings

log = logging.getLogger(__name__)
HH_SUBS_URL = "https://api.hh.ru/webhook/subscriptions"

# Карта поддерживаемых событий HH
# Список соответствует документации Webhook API (https://github.com/hhru/api)
EVENT_MAPPING = {
    "negotiation.created": "NEW_NEGOTIATION_VACANCY",
    "negotiation.status_changed": "CHANGE_NEGOTIATION_STATUS",
    "message.created": "NEW_NEGOTIATION_MESSAGE",
}


def _target_url() -> str:
    s = get_settings()
    return (getattr(s, "HH_WEBHOOK_URL", "") or "").strip()


def _actions() -> list[dict]:
    """
    Построить список словарей для передачи в actions.
    Читает HH_WEBHOOK_EVENTS (через запятую). Если переменная пуста,
    используется ['negotiation.created'] по умолчанию.
    """
    s = get_settings()
    raw = (getattr(s, "HH_WEBHOOK_EVENTS", "") or "").strip()
    tokens = [t.strip() for t in raw.split(",") if t.strip()] if raw else ["negotiation.created"]

    actions: list[dict] = []
    invalid: list[str] = []
    for token in tokens:
        key = token.lower().replace(" ", "")
        if key in EVENT_MAPPING:
            type_name = EVENT_MAPPING[key]
            if type_name == "NEW_NEGOTIATION_VACANCY":
                actions.append({"type": type_name, "settings": {"vacancies_only_mine": False}})
            else:
                actions.append({"type": type_name})
        else:
            invalid.append(token)

    if invalid:
        log.warning("HH webhook: unsupported events ignored: %s", ",".join(invalid))
    return actions


async def ensure_hh_webhook(client: httpx.AsyncClient) -> None:
    """Создать или обновить подписку HH вебхуков, используя первого доступного работодателя."""

    url = _target_url()
    if not url:
        log.info("HH webhook: HH_WEBHOOK_URL пуст — пропускаю регистрацию")
        return

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

    actions = _actions()
    if not actions:
        log.warning("HH webhook: no valid actions specified — skipping registration")
        return

    try:
        r = await client.get(HH_SUBS_URL, headers=headers, timeout=20)
        if r.status_code in (401, 403, 404):
            log.warning("HH webhook: %s — нет прав/токен/фича недоступна", r.status_code)
            return
        r.raise_for_status()
        js = r.json()
        items = js if isinstance(js, list) else js.get("items", [])

        current = next((it for it in items if str(it.get("url", "")).strip() == url), None)

        if not current:
            body = {"url": url, "actions": actions}
            cr = await client.post(HH_SUBS_URL, json=body, headers=headers, timeout=20)
            cr.raise_for_status()
            log.info("HH webhook: создано -> %s [%s]", url, ",".join([a["type"] for a in actions]))
            return

        current_types = sorted([a.get("type", "") for a in current.get("actions", [])])
        want_types = sorted([a["type"] for a in actions])
        if want_types != current_types:
            del_id = current.get("id") or current.get("subscription_id")
            if del_id:
                await client.delete(f"{HH_SUBS_URL}/{del_id}", headers=headers, timeout=20)
            cr = await client.post(HH_SUBS_URL, json={"url": url, "actions": actions},
                                   headers=headers, timeout=20)
            cr.raise_for_status()
            log.info("HH webhook: обновлено -> %s [%s]", url, ",".join([a["type"] for a in actions]))
        else:
            log.info("HH webhook: уже настроено -> %s [%s]", url, ",".join([a["type"] for a in actions]))

    except httpx.HTTPStatusError as e:
        log.exception("HH webhook: HTTP ошибка (%s): %s", e.response.status_code, e.response.text)
    except (httpx.HTTPError, ValueError) as e:
        log.exception("HH webhook: непредвиденная ошибка: %s", e)
