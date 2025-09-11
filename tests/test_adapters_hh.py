from urllib.parse import parse_qs

import pytest
import httpx

from app.adapters import hh


@pytest.mark.asyncio
async def test_hh_set_employer_state(monkeypatch, token_mock):
    async def fake_with_retry(coro, attempts, is_retryable):
        return await coro()

    monkeypatch.setattr(hh, "with_retry", fake_with_retry)
    token = token_mock

    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        assert request.headers["Authorization"] == f"Bearer {token}"
        assert request.headers["Accept"] == "application/json"
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await hh.set_employer_state("resp1", "interview", "emp1", client)

    assert captured["url"].endswith("/negotiations/resp1/interview")
    assert captured["method"] == "PUT"


@pytest.mark.asyncio
async def test_hh_send_message(monkeypatch, token_mock):
    async def fake_with_retry(coro, attempts, is_retryable):
        return await coro()

    monkeypatch.setattr(hh, "with_retry", fake_with_retry)
    token = token_mock

    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["form"] = parse_qs(request.content.decode())
        assert request.headers["Authorization"] == f"Bearer {token}"
        assert request.headers["Accept"] == "application/json"
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await hh.send_message("resp1", "hello", "emp1", client)

    assert captured["url"].endswith("/negotiations/resp1/messages")
    assert captured["form"] == {"message": ["hello"]}


@pytest.mark.asyncio
async def test_hh_send_message_error(monkeypatch, token_mock):
    async def fake_with_retry(coro, attempts, is_retryable):
        return await coro()

    monkeypatch.setattr(hh, "with_retry", fake_with_retry)

    def handler(request):
        return httpx.Response(500, json={"error": "fail"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(hh.HHError):
            await hh.send_message("resp1", "hello", None, client)


@pytest.mark.asyncio
async def test_hh_fetch_applicant_details(monkeypatch, token_mock):

    def handler(request):
        if request.url.path.endswith("/negotiations/resp1"):
            return httpx.Response(200, json={"resume": {"id": "res1"}})
        elif request.url.path.endswith("/resumes/res1"):
            assert request.url.query == b"with_contacts=true"
            return httpx.Response(
                200,
                json={
                    "area": {"name": "Moscow"},
                    "contact": [
                        {"kind": "phone", "value": {"formatted": "+1"}},
                        {"kind": "email", "value": "john@example.com"},
                    ],
                    "first_name": "John",
                    "last_name": "Doe",
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        data = await hh.fetch_applicant_details("resp1", "emp1", client)

    assert data == {
        "name": "John Doe",
        "city": "Moscow",
        "phone": "+1",
        "email": "john@example.com",
    }
