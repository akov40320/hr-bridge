import asyncio
import pytest

from app.store_chat import upsert_tg_link, get_by_user


@pytest.mark.asyncio
async def test_upsert_tg_link_updates_only_on_change(in_memory_db):
    user_id = 1
    bot_kind = "test"

    await upsert_tg_link(user_id, bot_kind, lead_id=100)
    link = await get_by_user(user_id, bot_kind)
    assert link is not None
    assert link.lead_id == 100
    first_updated_at = link.updated_at

    await asyncio.sleep(1)
    await upsert_tg_link(user_id, bot_kind, lead_id=100)
    link_same = await get_by_user(user_id, bot_kind)
    assert link_same.updated_at == first_updated_at
    assert link_same.lead_id == 100

    await asyncio.sleep(1)
    await upsert_tg_link(user_id, bot_kind, lead_id=200)
    link_updated = await get_by_user(user_id, bot_kind)
    assert link_updated.lead_id == 200
    assert link_updated.updated_at != first_updated_at
