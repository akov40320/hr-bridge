import pytest
import respx
import httpx
from app.adapters import amochats

@pytest.mark.asyncio
@respx.mock
async def test_ensure_chat_created_and_send_text(monkeypatch):
    # не ходим в прод
    monkeypatch.setattr(amochats, "_base", lambda: "https://amojo.test")

    scope_id = "scope-123"
    monkeypatch.setattr(amochats, "_get_client", lambda: type("C", (), {
        "scope_id": scope_id,
        "secret": "secret",
        "account_id": "acc-1",
        "channel_id": "ch-1",
        "sender_user_amojo_id": "manager-amojo-id",
    })())

    url = f"https://amojo.test/v2/origin/custom/{scope_id}"

    # одна и та же точка вызывается дважды → даём 2 ответа по очереди
    route = respx.post(url).mock(side_effect=[
        httpx.Response(200, json={"conversation": {"uuid": "conv-uuid-42"}}),  # ensure #1 (create/find)
        httpx.Response(200, json={"conversation": {"uuid": "conv-uuid-42"}}),  # ensure #1 (system msg)
        httpx.Response(200, json={"conversation": {"uuid": "conv-uuid-42"}}),  # ensure #2 (create/find)
        httpx.Response(200, json={"conversation": {"uuid": "conv-uuid-42"}}),  # ensure #2 (system msg)
        httpx.Response(200, json={"conversation": {"uuid": "conv-uuid-42"}}),  # send_text
    ])

    async with httpx.AsyncClient() as client:
        cid = await amochats.ensure_chat_created(
            lead_id=2046, tg_user_id=777, tg_user_name="testuser", client=client,
        )
        assert cid == "conv-uuid-42"

        cid2 = await amochats.send_text_from_client(
            lead_id=2046, text="hello", tg_user_id=777, tg_user_name="testuser",
            conversation_id=None, client=client,
        )
        assert cid2 == "conv-uuid-42"

    assert route.called
    assert route.calls.call_count == 5
