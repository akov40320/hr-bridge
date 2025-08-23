import typing
from app.http_client import get_http_client

T = typing.TypeVar("T")

async def perform_request(
    func: typing.Callable[..., typing.Awaitable[T]],
    *args: typing.Any,
    client=None,
    **kwargs: typing.Any,
) -> T:
    """Execute *func* with a shared HTTP client.

    If *client* is not provided, :func:`get_http_client` is used.
    Additional positional and keyword arguments are forwarded to *func*.
    """
    if client is None:
        client = get_http_client()
    return await func(*args, client=client, **kwargs)
