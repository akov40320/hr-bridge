import pytest
import httpx
import json

from app.adapters import amochats


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda client: amochats.connect_channel(client=client),
        lambda client: amochats.send_text_from_client(
            lead_id=1, text="hi", tg_user_id=1, client=client
        ),
        lambda client: amochats.send_text_from_manager(
            conversation_id="cid", user_id=1, user_name=None, avatar=None, text="hi", client=client
        ),
        lambda client: amochats.ensure_chat_created(
            lead_id=1, tg_user_id=1, tg_user_name=None, client=client
        ),
    ],
)
async def test_env_missing(monkeypatch, call):
    monkeypatch.setattr(amochats.settings, "AMO_CHATS_SCOPE_ID", "", raising=False)
    monkeypatch.setattr(amochats, "_client", None, raising=False)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
        with pytest.raises(amochats.AmoChatsError):
            await call(client)


@pytest.mark.asyncio
async def test_bind_chat_to_contact_fallback(monkeypatch):
    class DummyAC:
        scope_id = "sid"
        secret = "sec"
        account_id = "acc"
        channel_id = "chan"
        sender_user_amojo_id = "user"

    monkeypatch.setattr(amochats, "_get_client", lambda: DummyAC())

    def handler(request: httpx.Request):
        if request.url.path == f"/v2/origin/custom/{DummyAC.scope_id}/chats":
            return httpx.Response(200, json={"chat_id": "chat42"})
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        class DummyAmoClient:
            @classmethod
            async def create(cls, http_client):
                return DummyAmoClient()

            async def bind_chat_to_contact(self, contact_id, chat_id):
                response = httpx.Response(
                    400, text="Channel must be linked to your client"
                )
                raise httpx.HTTPStatusError(
                    "error",
                    request=httpx.Request("POST", "https://example.com"),
                    response=response,
                )

        import app.adapters.amo_client as amo_client_module

        monkeypatch.setattr(amo_client_module, "AmoClient", DummyAmoClient)

        called: dict[str, tuple[int, str]] = {}

        async def fake_bind(contact_id: int, chat_id: str, client: httpx.AsyncClient):
            called["args"] = (contact_id, chat_id)

        monkeypatch.setattr(amochats, "_bind_contact_via_amojo", fake_bind)

        await amochats.ensure_chat_created(
            lead_id=1,
            tg_user_id=1,
            tg_user_name="name",
            client=client,
            bind_contact_id=55,
        )

        assert called["args"] == (55, "chat42")


@pytest.mark.asyncio
async def test_bind_contact_via_amojo(monkeypatch):
    class DummyAC:
        scope_id = "sid"
        secret = "sec"
        account_id = "acc"
        channel_id = "chan"
        sender_user_amojo_id = "user"

    monkeypatch.setattr(amochats, "_get_client", lambda: DummyAC())

    captured: dict[str, str] = {}

    def handler(request: httpx.Request):
        captured["path"] = request.url.path
        captured["body"] = request.content.decode()
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await amochats._bind_contact_via_amojo(123, "chatX", client)

    assert captured["path"] == f"/v2/origin/custom/{DummyAC.scope_id}/contacts"
    assert json.loads(captured["body"]) == {"contact_id": 123, "chat_id": "chatX"}

