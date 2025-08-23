import logging
import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.db.token_store import DbTokenStore
from app.core.config import get_settings

log = logging.getLogger(__name__)
HH_SUBS_URL = "https://api.hh.ru/webhook/subscriptions"

# Set of supported HH.ru webhook events based on API contract.
# This replaces the incorrect EVENT_MAPPING dictionary.
SUPPORTED_EVENTS = {
    "negotiation.created",
    "negotiation.status_changed",
    "message.created",
}


def _target_url() -> str:
    s = get_settings()
    return (getattr(s, "HH_WEBHOOK_URL", "") or "").strip()


def _actions() -> list[dict]:
    """
    Build the list of action dictionaries for the API request.
    Reads HH_WEBHOOK_EVENTS (comma-separated). If the variable is empty,
    it defaults to ['negotiation.created'].
    """
    s = get_settings()
    raw = (getattr(s, "HH_WEBHOOK_EVENTS", "") or "").strip()
    tokens = [t.strip() for t in raw.split(",") if t.strip()] if raw else ["negotiation.created"]

    actions: list[dict] =
    invalid: list[str] =
    for token in tokens:
        # Use the token directly, after validation.
        if token in SUPPORTED_EVENTS:
            # The special case for 'negotiation.created' is preserved.
            if token == "negotiation.created":
                actions.append({"type": token, "settings": {"vacancies_only_mine": False}})
            else:
                actions.append({"type": token})
        else:
            invalid.append(token)

    if invalid:
        log.warning("HH webhook: Unsupported or invalid events ignored: %s", ", ".join(invalid))
    return actions


async def ensure_hh_webhook(client: httpx.AsyncClient) -> None:
    """Create or update the HH webhook subscription using the first available employer."""

    url = _target_url()
    if not url:
        log.info("HH webhook: HH_WEBHOOK_URL is not set — skipping registration")
        return

    try:
        owners = await DbTokenStore.list_owners("hh")
        if not owners:
            raise RuntimeError("No employers found in the database")
        employer_id = owners
        tok = await DbTokenStore("hh", employer_id).load()
    except (RuntimeError, SQLAlchemyError) as e:
        log.info("HH webhook: Could not retrieve employer token — skipping registration. Reason: %s", e)
        return

    headers = {
        "Authorization": f"Bearer {tok['access_token']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "HH-User-Agent": "hr-bridge/1.0 (+https://hr-bridge.onrender.com; ops@hr-bridge.onrender.com)",
    }

    actions = _actions()
    if not actions:
        log.warning("HH webhook: No valid actions specified in configuration — skipping registration")
        return

    try:
        r = await client.get(HH_SUBS_URL, headers=headers, timeout=20)
        
        # Handle cases where webhooks might be disabled for the account
        if r.status_code in (403, 404):
            log.warning("HH webhook: Feature unavailable or insufficient permissions (%s). Please check employer account settings.", r.status_code)
            return
        # Handle token expiration separately
        if r.status_code == 401:
            log.warning("HH webhook: Unauthorized (401). The employer token may be expired or invalid.")
            return

        r.raise_for_status()
        
        # The response for GET /subscriptions can be a list directly or an object with an 'items' key.
        js = r.json()
        items = js if isinstance(js, list) else js.get("items",)

        current = next((it for it in items if str(it.get("url", "")).strip() == url), None)
        
        # Sort lists of event types to ensure consistent comparison
        want_types = sorted([a["type"] for a in actions])

        if not current:
            body = {"url": url, "actions": actions}
            cr = await client.post(HH_SUBS_URL, json=body, headers=headers, timeout=20)
            cr.raise_for_status()
            log.info("HH webhook: Created subscription for -> %s [%s]", url, ", ".join(want_types))
            return

        current_types = sorted([a.get("type", "") for a in current.get("actions",)])
        
        if want_types!= current_types:
            # The API requires deleting the old subscription before creating a new one with updated actions.
            del_id = current.get("id") or current.get("subscription_id")
            if del_id:
                del_resp = await client.delete(f"{HH_SUBS_URL}/{del_id}", headers=headers, timeout=20)
                # Log a warning if deletion fails but proceed with creation attempt
                if not del_resp.is_success:
                    log.warning("HH webhook: Failed to delete existing subscription (ID: %s), proceeding with creation. Status: %s", del_id, del_resp.status_code)

            cr = await client.post(HH_SUBS_URL, json={"url": url, "actions": actions}, headers=headers, timeout=20)
            cr.raise_for_status()
            log.info("HH webhook: Updated subscription for -> %s [%s]", url, ", ".join(want_types))
        else:
            log.info("HH webhook: Subscription already configured correctly for -> %s [%s]", url, ", ".join(want_types))

    except httpx.HTTPStatusError as e:
        # Log the request body on error for easier debugging
        request_body = e.request.content.decode('utf-8') if e.request.content else "No Body"
        log.exception(
            "HH webhook: HTTP error (%s) during subscription management. Request Body: %s. Response: %s",
            e.response.status_code,
            request_body,
            e.response.text
        )
    except (httpx.RequestError, ValueError) as e:
        log.exception("HH webhook: Network or JSON parsing error during subscription management: %s", e)
