# app/hh_webhooks.py
import logging
import httpx
from app.token_store import DbTokenStore
from app.config import settings

log = logging.getLogger(__name__)

HH_SUBS_URL = "https://api.hh.ru/webhook-subscriptions"


def _target_url() -> str:
    # теперь только явная настройка
    return (getattr(settings, "HH_WEBHOOK_URL", "") or "").strip()


def _events() -> list[str]:
    raw = (getattr(settings, "HH_WEBHOOK_EVENTS", "") or "").strip()
    if raw:
        return [e.strip() for e in raw.split(",") if e.strip()]
    return ["negotiation_created"]


async def ensure_hh_webhook() -> None:
    url = _target_url()
    if not url:
        log.info("HH webhook: HH_WEBHOOK_URL пуст — пропускаю регистрацию")
        return

    try:
        tok = await DbTokenStore("hh").load()
    except Exception:
        log.info("HH webhook: нет токена работодателя — пропускаю регистрацию")
        return

    headers = {
        "Authorization": f"Bearer {tok['access_token']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    want_events = _events()

    try:
        async with httpx.AsyncClient(timeout=20) as x:
            r = await x.get(HH_SUBS_URL, headers=headers)
            r.raise_for_status()
            js = r.json()
            items = js if isinstance(js, list) else js.get("items", [])

            current = None
            for it in items:
                if str(it.get("url", "")).strip() == url:
                    current = it
                    break

            if not current:
                body = {"url": url, "events": want_events}
                cr = await x.post(HH_SUBS_URL, json=body, headers=headers)
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
                    await x.delete(f"{HH_SUBS_URL}/{del_id}", headers=headers)
                cr = await x.post(HH_SUBS_URL, json={"url": url, "events": want_events}, headers=headers)
                cr.raise_for_status()
                log.info("HH webhook: обновлено -> %s [%s]", url, ",".join(want_events))
            else:
                log.info("HH webhook: уже настроено -> %s [%s]", url, ",".join(want_events))

    except httpx.HTTPStatusError as e:
        log.exception("HH webhook: HTTP error (%s): %s", e.response.status_code, e.response.text)
    except Exception:
        log.exception("HH webhook: unexpected error")
