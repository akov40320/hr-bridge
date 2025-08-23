"""Ensure HH webhook subscriptions are configured as expected."""

import logging
import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.db.token_store import DbTokenStore
from app.core.config import get_settings

log = logging.getLogger(__name__)
HH_SUBS_URL = "https://api.hh.ru/webhook/subscriptions"

ALLOWED_ACTIONS: set[str] = {
    "negotiation_created",         # создание отклика/переписки
    "message_created",             # появление нового сообщения
    "negotiation_status_changed",  # изменение статуса отклика
}

# Словарь для явного сопоставления форматов из документации (точки) к
# формату с подчёркиваниями, который ожидает API.
EVENT_ALIASES: dict[str, str] = {
    "negotiation.created": "negotiation_created",
    "message.created": "message_created",
    "negotiation.status_changed": "negotiation_status_changed",
}


def _target_url() -> str:
    s = get_settings()
    return (getattr(s, "HH_WEBHOOK_URL", "") or "").strip()


def _events() -> list[str]:
    """Вернуть нормализованный список разрешённых событий HH."""
    s = get_settings()
    raw = (getattr(s, "HH_WEBHOOK_EVENTS", "") or "").strip()
    tokens = [t.strip() for t in raw.split(",") if t.strip()] if raw else []
    if not tokens:
        tokens = ["negotiation_created"]
    normalised: list[str] = []
    for token in tokens:
        # если в переменной окружения указаны названия через точку — заменяем
        alias = EVENT_ALIASES.get(token) or EVENT_ALIASES.get(token.lower())
        # иначе заменяем точки и дефисы на подчёркивания
        if not alias:
            alias = token.lower().replace(".", "_").replace("-", "_")
        normalised.append(alias)
    # удалить дубликаты, сохранить порядок
    seen = set()
    unique = [e for e in normalised if not (e in seen or seen.add(e))]
    allowed = [e for e in unique if e in ALLOWED_ACTIONS]
    invalid = [e for e in unique if e not in ALLOWED_ACTIONS]
    if invalid:
        log.warning("HH webhook: unsupported events ignored: %s", ",".join(invalid))
    return allowed


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
    }
    want_events = _events()

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
            body = {"url": url, "events": want_events}
            cr = await client.post(HH_SUBS_URL, json=body, headers=headers, timeout=20)
            if cr.status_code in (401, 403, 404):
                log.warning("HH webhook: %s — нет прав/токен/фича недоступна", cr.status_code)
                return
            cr.raise_for_status()
            log.info("HH webhook: создано -> %s [%s]", url, ",".join(want_events))
            return

        have_events = sorted([e.strip() for e in current.get("events", [])])
        if sorted(want_events) != have_events:
            del_id = current.get("id") or current.get("subscription_id")
            if del_id:
                await client.delete(f"{HH_SUBS_URL}/{del_id}", headers=headers, timeout=20)
            cr = await client.post(
                HH_SUBS_URL,
                json={"url": url, "events": want_events},
                headers=headers,
                timeout=20,
            )
            cr.raise_for_status()
            log.info("HH webhook: обновлено -> %s [%s]", url, ",".join(want_events))
        else:
            log.info("HH webhook: уже настроено -> %s [%s]", url, ",".join(want_events))

    except httpx.HTTPStatusError as e:
        log.exception("HH webhook: HTTP ошибка (%s): %s", e.response.status_code, e.response.text)
    except (httpx.HTTPError, ValueError) as e:
        log.exception("HH webhook: непредвиденная ошибка: %s", e)
