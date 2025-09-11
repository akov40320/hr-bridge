import pytest
from app.store_chat import upsert_tg_link, set_conversation
from app.api.api_amochats import resolve_links

@pytest.mark.asyncio
async def test_resolve_links_uses_client_conv_id(in_memory_db):
    user_id = 123
    bot_kind = "master"
    lead_id = 20832209
    conv_client_id = "contact:21982943"
    chat_id = "97ddeb13-db49-4988-8160-5db861425fc2"

    await upsert_tg_link(user_id, bot_kind, lead_id)
    await set_conversation(user_id, bot_kind, conv_client_id)

    links = await resolve_links(chat_id, conv_client_id, None, {}, {})
    assert len(links) == 1
    assert links[0].user_id == user_id
    assert links[0].conversation_id == conv_client_id
