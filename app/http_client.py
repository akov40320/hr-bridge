import httpx


# Shared HTTP client instance. Created lazily on first use.
_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return a singleton :class:`httpx.AsyncClient` instance.

    The client is instantiated on first access and reused afterwards.
    """

    global _http_client

    if _http_client is None:
        _http_client = httpx.AsyncClient()

    return _http_client


async def close_http_client() -> None:
    """Close the shared AsyncClient instance."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
