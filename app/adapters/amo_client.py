"""Клиент для работы с AmoCRM API."""

import time
import logging
import httpx
from app.core.config import get_settings
from app.db.token_store import TokenData, DbTokenStore

logger = logging.getLogger(__name__)


class ReauthRequired(Exception):
    """Требуется переавторизация в AmoCRM."""


class AmoClient:
    """Высокоуровневый клиент для HTTP‑API AmoCRM."""

    def __init__(self, tokens: TokenData, store: DbTokenStore, client: httpx.AsyncClient):
        """Инициализация клиента: базовый URL, токены и HTTP‑клиент."""
        self._s = get_settings()
        self.base = self._s.AMO_BASE_URL.rstrip("/")
        self.store = store
        self._access = tokens["access_token"]
        self._refresh = tokens["refresh_token"]
        self._expires_at = tokens["expires_at"]
        self.client = client

    @classmethod
    async def create(cls, client: httpx.AsyncClient):
        """Фабричный метод: создать клиент, загрузив токены из хранилища."""
        store = DbTokenStore("amo")
        tokens = await store.load()
        return cls(tokens, store, client)

    @property
    def headers(self):
        """Стандартные заголовки запросов к AmoCRM."""
        return {"Authorization": f"Bearer {self._access}", "Accept": "application/json"}

    async def _refresh_token(self) -> None:
        """Обновляет access‑токен и refresh‑токен."""
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
        """Гарантирует, что токен не истёк."""
        if time.time() >= self._expires_at - 120:
            await self._refresh_token()

    async def _request(self, method: str, url: str, **kw):
        """Выполняет HTTP‑запрос, при 401 обновляет токен; логирует и поднимает ошибки."""
        await self._ensure_token()
        r = await self.client.request(method, url, headers=self.headers, timeout=30, **kw)
        if r.status_code == 401:
            await self._refresh_token()
            r = await self.client.request(method, url, headers=self.headers, timeout=30, **kw)
        if r.is_error:
            payload = kw.get("json") or kw.get("data")
            logger.error(
                "AMO ошибка запроса: status=%s, text=%s, url=%s, payload=%s",
                r.status_code,
                r.text,
                getattr(r, "url", url),
                payload,
            )
            r.raise_for_status()
        return r.json() if r.content else None

    async def create_leads(self, leads: list[dict]):
        """Создать сделки (leads) в AmoCRM."""
        url = f"{self.base}/api/v4/leads"
        return await self._request("POST", url, json=leads)

    async def add_tags(self, lead_id: int, tags: list[str]):
        """Добавить теги к сделке."""
        url = f"{self.base}/api/v4/leads"
        body = [{"id": lead_id, "_embedded": {"tags": [{"name": t} for t in tags]}}]
        return await self._request("PATCH", url, json=body)

    async def add_note(self, lead_id: int, text: str):
        """Добавить обычную заметку к сделке."""
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
        """Создать контакт с опциональными телефоном и email."""
        url = f"{self.base}/api/v4/contacts"
        cfv = []
        if phone:
            cfv.append({"field_code": "PHONE", "values": [{"value": phone}]})
        if email:
            cfv.append({"field_code": "EMAIL", "values": [{"value": email}]})
        body = [{"name": name, **({"custom_fields_values": cfv} if cfv else {})}]
        return await self._request("POST", url, json=body)

    async def link_contact_to_lead(self, lead_id: int, contact_id: int):
        """Привязать контакт к сделке."""
        url = f"{self.base}/api/v4/leads/{lead_id}/link"
        body = [{"to_entity_id": contact_id, "to_entity_type": "contacts"}]
        return await self._request("POST", url, json=body)

    async def update_status(self, lead_id: int, status_id: int):
        """Обновить статус (status) сделки."""
        url = f"{self.base}/api/v4/leads"
        body = [{"id": lead_id, "status_id": status_id}]
        return await self._request("PATCH", url, json=body)

    async def update_lead_custom_fields(self, lead_id: int, fields: dict[int, str]):
        """Обновить пользовательские поля у сделки: поле -> значение."""
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
        """Получить данные сделки по идентификатору."""
        url = f"{self.base}/api/v4/leads/{lead_id}"
        return await self._request("GET", url)

    async def get_lead_with_contacts(self, lead_id: int):
        """Получить сделку со встраиваемыми контактами (embedded)."""
        url = f"{self.base}/api/v4/leads/{int(lead_id)}?with=contacts"
        return await self._request("GET", url)

    async def get_lead_with_loss_reason(self, lead_id: int):
        """Получить сделку с вложенной причиной отказа (with=loss_reason)."""
        url = f"{self.base}/api/v4/leads/{int(lead_id)}?with=loss_reason"
        return await self._request("GET", url)

    async def bind_chat_to_contact(self, contact_id: int, chat_id: str):
        """Привязать чат к контакту (POST /api/v4/contacts/chats).

        AmoCRM ожидает, что ``scope_id`` будет соответствовать интеграции,
        зарегистрированной в AmoChats API. Иначе возможна ошибка
        ``Channel must be linked to your client``. Укажите корректный
        ``AMO_CHATS_SCOPE_ID`` в настройках на стороне Amo и в конфигурации
        приложения (значение, полученное при регистрации канала).
        """
        url = f"{self.base}/api/v4/contacts/chats"
        body = [
            {
                "contact_id": int(contact_id),
                "chat_id": str(chat_id),
                "scope_id": self._s.AMO_CHATS_SCOPE_ID,
            }
        ]
        return await self._request("POST", url, json=body)
