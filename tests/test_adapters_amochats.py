import pytest
import httpx

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

