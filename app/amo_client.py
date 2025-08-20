import time, httpx
from app.config import settings
from app.token_store import TokenData, DbTokenStore


class ReauthRequired(Exception):
    pass


class AmoClient:
    def __init__(self, tokens: TokenData, store: DbTokenStore):
        self.base = settings.AMO_BASE_URL.rstrip("/")
        self.store = store
        self._access = tokens["access_token"]
        self._refresh = tokens["refresh_token"]
        self._expires_at = tokens["expires_at"]

    @classmethod
    async def create(cls):
        store = DbTokenStore("amo")
        tokens = await store.load()
        return cls(tokens, store)

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self._access}", "Accept": "application/json"}

    async def _refresh_token(self) -> None:
        url = f"{self.base}/oauth2/access_token"
        payload = {
            "client_id": settings.AMO_CLIENT_ID,
            "client_secret": settings.AMO_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": self._refresh,
            "redirect_uri": settings.AMO_REDIRECT_URI,
        }
        async with httpx.AsyncClient(timeout=30) as x:
            r = await x.post(url, json=payload)
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
            expires_at=self._expires_at
        ))

    async def _ensure_token(self):
        if time.time() >= self._expires_at - 120:
            await self._refresh_token()

    async def _request(self, method: str, url: str, **kw):
        await self._ensure_token()
        async with httpx.AsyncClient(timeout=30) as x:
            r = await x.request(method, url, headers=self.headers, **kw)
        if r.status_code == 401:
            await self._refresh_token()
            async with httpx.AsyncClient(timeout=30) as x:
                r = await x.request(method, url, headers=self.headers, **kw)
        if r.is_error:
            print("AMO ERROR:", r.status_code, r.text)
            r.raise_for_status()
        return r.json() if r.content else None

    async def create_leads(self, leads: list[dict]):
        url = f"{self.base}/api/v4/leads"
        return await self._request("POST", url, json=leads)

    async def add_tags(self, lead_id: int, tags: list[str]):
        url = f"{self.base}/api/v4/leads"
        body = [{"id": lead_id, "_embedded": {"tags": [{"name": t} for t in tags]}}]
        return await self._request("PATCH", url, json=body)

    async def add_note(self, lead_id: int, text: str):
        # Заметка в таймлайн сделки (общая заметка)
        url = f"{self.base}/api/v4/leads/notes"
        body = [{
            "entity_id": lead_id,
            "note_type": "common",
            "params": {"text": text}
        }]
        return await self._request("POST", url, json=body)

    async def create_contact(self, name: str, phone: str | None = None):
        url = f"{self.base}/api/v4/contacts"
        body = [{
            "name": name,
            **({"custom_fields_values": [
                {"field_code": "PHONE", "values": [{"value": phone}]}
            ]} if phone else {})
        }]
        return await self._request("POST", url, json=body)

    async def link_contact_to_lead(self, lead_id: int, contact_id: int):
        url = f"{self.base}/api/v4/leads/{lead_id}/link"
        body = [{"to_entity_id": contact_id, "to_entity_type": "contacts"}]
        return await self._request("POST", url, json=body)

    async def update_lead_custom_fields(self, lead_id: int, fields: dict[int, str]):
        if not fields:
            return None
        url = f"{self.base}/api/v4/leads"
        cfv = [{"field_id": fid, "values": [{"value": val}]} for fid, val in fields.items() if val is not None]
        body = [{"id": lead_id, "custom_fields_values": cfv}]
        return await self._request("PATCH", url, json=body)

    async def get_lead(self, lead_id: int):
              url = f"{self.base}/api/v4/leads/{lead_id}"
              return await self._request("GET", url)