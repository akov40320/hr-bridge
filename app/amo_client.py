import time
import httpx
from app.config import settings
from app.token_store import FileTokenStore, TokenData


class AmoClient:
    def __init__(self, store: FileTokenStore | None = None):
        self.base = settings.AMO_BASE_URL.rstrip("/")
        self.store = store or FileTokenStore()
        data = self.store.load()
        self._access = data["access_token"]
        self._refresh = data["refresh_token"]
        self._expires_at = data["expires_at"]

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
        r.raise_for_status()
        data = r.json()
        # Если Amo вернул server_time — используем его; иначе текущее время
        server_time = data.get("server_time", int(time.time()))
        expires_in = int(data.get("expires_in", 3600))
        expires_at = server_time + expires_in - 120  # запас 2 минуты

        self._access = data["access_token"]
        self._refresh = data["refresh_token"]
        self._expires_at = expires_at

        self.store.save(TokenData(
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
        r.raise_for_status()
        return r.json() if r.content else None

    async def create_leads(self, leads: list[dict]):
        url = f"{self.base}/api/v4/leads"
        return await self._request("POST", url, json=leads)

    async def add_tags(self, lead_id: int, tags: list[str]):
        url = f"{self.base}/api/v4/leads"
        body = [{"id": lead_id, "_embedded": {"tags": [{"name": t} for t in tags]}}]
        return await self._request("PATCH", url, json=body)
