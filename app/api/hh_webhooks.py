"""Обеспечивает корректную регистрацию подписок HH вебхуков."""

import logging
import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.db.token_store import DbTokenStore
from app.core.config import get_settings

log = logging.getLogger(__name__)
HH_SUBS_URL = "https://api.hh.ru/webhook/subscriptions"

ALLOWED_TYPES = {
    "NEW_NEGOTIATION_VACANCY",
    "NEW_NEGOTIATION_MESSAGE",
    "NEGOTIATION_EMPLOYER_STATE_CHANGE",
}

ALIAS2TYPE = {
    "negotiation.created": "NEW_NEGOTIATION_VACANCY",
    "negotiation_created": "NEW_NEGOTIATION_VACANCY",
    "NEW_NEGOTIATION_VACANCY": "NEW_NEGOTIATION_VACANCY",
    "message.created": "NEW_NEGOTIATION_MESSAGE",
    "message_created": "NEW_NEGOTIATION_MESSAGE",
    "NEW_NEGOTIATION_MESSAGE": "NEW_NEGOTIATION_MESSAGE",
    "negotiation.status.changed": "NEGOTIATION_EMPLOYER_STATE_CHANGE",
    "negotiation.status_changed": "NEGOTIATION_EMPLOYER_STATE_CHANGE",
    "NEGOTIATION_EMPLOYER_STATE_CHANGE": "NEGOTIATION_EMPLOYER_STATE_CHANGE",
}


def _target_url() -> str:
    s = get_settings()
    return (getattr(s, "HH_WEBHOOK_URL", "") or "").strip()


def _hh_user_agent() -> str:
    s = get_settings()
    ua = (getattr(s, "HH_USER_AGENT", "") or "").strip()
    return ua or "hr-bridge/1.0 (https://hr-bridge.onrender.com)"


def _wanted_types() -> list[str]:
    s = get_settings()
    raw = (getattr(s, "HH_WEBHOOK_EVENTS", "") or "").strip()
    items = [e.strip() for e in raw.split(",") if e.strip()] if raw else []
    if not items:
        items = ["NEW_NEGOTIATION_VACANCY"]
    mapped = [ALIAS2TYPE.get(x, x) for x in items]
    invalid = [t for t in mapped if t not in ALLOWED_TYPES]
    if invalid:
        log.warning("HH webhook: неподдерживаемые типы проигнорированы: %s", ",".join(invalid))
    return [t for t in mapped if t in ALLOWED_TYPES]


def _build_actions(types: list[str]) -> list[dict]:
    out: list[dict] = []
    for t in types:
        if t == "NEW_NEGOTIATION_VACANCY":
            out.append({"type": t, "settings": {"vacancies_only_mine": False}})
        else:
            out.append({"type": t})
    return out


async def ensure_hh_webhook(client: httpx.AsyncClient) -> None:
    """Создать или обновить подписку HH вебхуков (берётся первый доступный работодатель)."""

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
        "HH-User-Agent": _hh_user_agent(),
    }

    want_types = _wanted_types()
    if not want_types:
        log.warning("HH webhook: нет валидных типов действий — пропускаю регистрацию")
        return
    want_actions = _build_actions(want_types)

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
            body = {"url": url, "actions": want_actions}
            cr = await client.post(HH_SUBS_URL, json=body, headers=headers, timeout=20)
            cr.raise_for_status()
            log.info("HH webhook: создано -> %s [%s]", url, ",".join(want_types))
            return

        current_types = sorted([a.get("type", "") for a in current.get("actions", [])])
        if sorted(want_types) != current_types:
            del_id = current.get("id") or current.get("subscription_id")
            if del_id:
                await client.delete(f"{HH_SUBS_URL}/{del_id}", headers=headers, timeout=20)
            cr = await client.post(
                HH_SUBS_URL,
                json={"url": url, "actions": want_actions},
                headers=headers,
                timeout=20,
            )
            cr.raise_for_status()
            log.info("HH webhook: обновлено -> %s [%s]", url, ",".join(want_types))
        else:
            log.info("HH webhook: уже настроено -> %s [%s]", url, ",".join(want_types))

    except httpx.HTTPStatusError as e:
        log.exception("HH webhook: HTTP ошибка (%s): %s", e.response.status_code, e.response.text)
    except (httpx.HTTPError, ValueError) as e:
        log.exception("HH webhook: непредвиденная ошибка: %s", e)
