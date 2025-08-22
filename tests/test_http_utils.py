import os
import sys
import httpx
import pytest
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.http_utils import send_with_retry


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _sleep(_):
        pass

    monkeypatch.setattr("app.core.retry.asyncio.sleep", _sleep)


def test_send_with_retry_retries_and_returns_response():
    responses = [
        httpx.Response(500, request=httpx.Request("POST", "http://test")),
        httpx.Response(200, request=httpx.Request("POST", "http://test")),
    ]
    calls = 0

    async def request_fn(_):
        nonlocal calls
        resp = responses[calls]
        calls += 1
        return resp

    async def run():
        async with httpx.AsyncClient() as client:
            return await send_with_retry(client, request_fn, lambda s: s == 500)

    resp = asyncio.run(run())

    assert resp.status_code == 200
    assert calls == 2


def test_send_with_retry_non_retryable_raises():
    responses = [httpx.Response(400, request=httpx.Request("POST", "http://test"))]

    async def request_fn(_):
        return responses[0]

    async def run():
        async with httpx.AsyncClient() as client:
            await send_with_retry(client, request_fn, lambda s: s == 500)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())


def test_send_with_retry_exhausts_attempts():
    responses = [
        httpx.Response(500, request=httpx.Request("POST", "http://test"))
        for _ in range(5)
    ]
    calls = 0

    async def request_fn(_):
        nonlocal calls
        resp = responses[calls]
        calls += 1
        return resp

    async def run():
        async with httpx.AsyncClient() as client:
            await send_with_retry(client, request_fn, lambda s: s == 500)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())

    assert calls == 5
