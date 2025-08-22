import httpx

_http_client: httpx.AsyncClient | None = httpx.AsyncClient()


def get_http_client() -> httpx.AsyncClient:
    """Return a singleton AsyncClient instance."""
    assert _http_client is not None
    return _http_client


async def close_http_client() -> None:
    """Close the shared AsyncClient instance."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
