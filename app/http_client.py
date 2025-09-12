"""Utilities for a shared HTTP client.

This module exposes :func:`get_http_client` to obtain a lazily created
:class:`httpx.AsyncClient` that is reused across the application. The
client is instantiated with a default timeout of 30 seconds to avoid
hanging requests. Call :func:`close_http_client` on application shutdown
to properly release resources held by the client.
"""

import httpx


class _HttpClientFactory:
    """Factory managing a shared :class:`httpx.AsyncClient` instance."""

    _client: httpx.AsyncClient | None = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        """Return the shared AsyncClient instance."""
        if cls._client is None:
            cls._client = httpx.AsyncClient(timeout=30)
        return cls._client

    @classmethod
    async def close_client(cls) -> None:
        """Close and discard the shared client instance."""
        if cls._client is not None:
            await cls._client.aclose()
            cls._client = None


def get_http_client() -> httpx.AsyncClient:
    """Return the shared :class:`httpx.AsyncClient` instance."""
    return _HttpClientFactory.get_client()


async def close_http_client() -> None:
    """Close the shared :class:`httpx.AsyncClient` instance."""
    await _HttpClientFactory.close_client()
