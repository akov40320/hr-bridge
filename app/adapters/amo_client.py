"""Client for interacting with the AmoCRM API."""

import time
import logging
import httpx
from app.core.config import get_settings
from app.db.token_store import TokenData, DbTokenStore

logger = logging.getLogger(__name__)


class ReauthRequired(Exception):
    """Raised when reauthorization with AmoCRM is required."""


class AmoClient:
    """High level wrapper around the AmoCRM HTTP API."""

    def __init__(self, tokens: TokenData, store: DbTokenStore, client: httpx.AsyncClient):
        """Initialize the client with token data and an HTTP client."""
        self._s = get_settings()
        self.base = self._s.AMO_BASE_URL.rstrip("/")
        self.store = store
        self._access = tokens["access_token"]
        self._refresh = tokens["refresh_token"]
        self._expires_at = tokens["expires_at"]
        self.client = client

    @classmethod
    async def create(cls, client: httpx.AsyncClient):
        """Factory method building the client using tokens from storage."""
        store = DbTokenStore("amo")
        tokens = await store.load()
        return cls(tokens, store, client)

    @property
    def headers(self):
        """Default headers for AmoCRM requests."""
        return {"Authorization": f"Bearer {self._access}", "Accept": "application/json"}

    async def _refresh_token(self) -> None:
        """Refresh an expired access token using the refresh token."""
        url = f"{self.base}/oauth2/access_token"
        payload = {
            "client_id": self._s.AMO_CLIENT_ID,
            "client_secret": self._s.AMO_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": self._refresh,
            "redirect_uri": self._s.AMO_REDIRECT_URI,
        }
        r = await self.client.post(url, json=payload, timeout=30)
        if r.status_code in (400, 401) and "invalid_grant" in (r.text or "").lower():
            raise ReauthRequired("Amo refresh_token invalid_grant")
        r.raise_for_status()

        data = r.json()
        server_time = int(data.get("server_time", time.time()))
        expires_in = int(data.get("expires_in", 3600))
        self._access = data["access_token"]
        self._refresh = data["refresh_token"]
        self._expires_at = server_time + expires_in - 120

        await self.store.save(TokenData(
            access_token=self._access,
            refresh_token=self._refresh,
            expires_at=self._expires_at,
        ))

    async def _ensure_token(self):
        """Refresh the token if it will expire soon."""
        if time.time() >= self._expires_at - 120:
            await self._refresh_token()

    async def _request(self, method: str, url: str, **kw):
        """Send an HTTP request handling token refresh and error logging."""
        await self._ensure_token()
        r = await self.client.request(method, url, headers=self.headers, timeout=30, **kw)
        if r.status_code == 401:
            await self._refresh_token()
            r = await self.client.request(method, url, headers=self.headers, timeout=30, **kw)
        if r.is_error:
            payload = kw.get("json") or kw.get("data")
            logger.error(
                "AMO ERROR: status=%s, text=%s, url=%s, payload=%s",
                r.status_code,
                r.text,
                getattr(r, "url", url),
                payload,
            )
            r.raise_for_status()
        return r.json() if r.content else None

    async def create_leads(self, leads: list[dict]):
        """Create AmoCRM leads in bulk."""
        url = f"{self.base}/api/v4/leads"
        return await self._request("POST", url, json=leads)

    async def add_tags(self, lead_id: int, tags: list[str]):
        """Attach tags to a lead."""
        url = f"{self.base}/api/v4/leads"
        body = [{"id": lead_id, "_embedded": {"tags": [{"name": t} for t in tags]}}]
        return await self._request("PATCH", url, json=body)

    async def add_note(self, lead_id: int, text: str):
        """Add a common note to a lead's timeline."""
        url = f"{self.base}/api/v4/leads/notes"
        body = [{
            "entity_id": lead_id,
            "note_type": "common",
            "params": {"text": text},
        }]
        return await self._request("POST", url, json=body)

    async def create_contact(
        self, name: str, phone: str | None = None, email: str | None = None
    ):
        """Create a contact with optional phone and email."""
        url = f"{self.base}/api/v4/contacts"
        cfv = []
        if phone:
            cfv.append({"field_code": "PHONE", "values": [{"value": phone}]})
        if email:
            cfv.append({"field_code": "EMAIL", "values": [{"value": email}]})
        body = [{"name": name, **({"custom_fields_values": cfv} if cfv else {})}]
        return await self._request("POST", url, json=body)

    async def link_contact_to_lead(self, lead_id: int, contact_id: int):
        """Link a contact to a lead."""
        url = f"{self.base}/api/v4/leads/{lead_id}/link"
        body = [{"to_entity_id": contact_id, "to_entity_type": "contacts"}]
        return await self._request("POST", url, json=body)

    async def update_lead_custom_fields(self, lead_id: int, fields: dict[int, str]):
        """Update custom field values for a lead."""
        if not fields:
            return None
        url = f"{self.base}/api/v4/leads"
        cfv = [
            {"field_id": fid, "values": [{"value": val}]}
            for fid, val in fields.items()
            if val is not None
        ]
        body = [{"id": lead_id, "custom_fields_values": cfv}]
        return await self._request("PATCH", url, json=body)

    async def get_lead(self, lead_id: int):
        """Retrieve a lead by its identifier."""
        url = f"{self.base}/api/v4/leads/{lead_id}"
        return await self._request("GET", url)
