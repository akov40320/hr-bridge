"""Утилиты для общего HTTP‑клиента.

Модуль предоставляет :func:`get_http_client` для ленивого создания и
повторного использования :class:`httpx.AsyncClient` в приложении. Клиент
создаётся с таймаутом по умолчанию 30 секунд, чтобы избежать «зависаний».
Для корректного завершения вызовите :func:`close_http_client` при остановке.
"""

import httpx


class _HttpClientFactory:
    """Фабрика, управляющая общим экземпляром :class:`httpx.AsyncClient`."""

    _client: httpx.AsyncClient | None = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        """Вернуть общий экземпляр AsyncClient."""
        if cls._client is None:
            cls._client = httpx.AsyncClient(timeout=30)
        return cls._client

    @classmethod
    async def close_client(cls) -> None:
        """Закрыть и сбросить общий экземпляр клиента."""
        if cls._client is not None:
            await cls._client.aclose()
            cls._client = None


def get_http_client() -> httpx.AsyncClient:
    """Вернуть общий экземпляр :class:`httpx.AsyncClient`."""
    return _HttpClientFactory.get_client()


async def close_http_client() -> None:
    """Закрыть общий экземпляр :class:`httpx.AsyncClient`."""
    await _HttpClientFactory.close_client()
