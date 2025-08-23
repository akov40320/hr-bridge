"""Persistence helpers for mapping Telegram chats to leads and conversations."""

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql.functions import now

from app.db import get_session
from app.db.models import TgLink


async def upsert_tg_link(user_id: int, bot_kind: str, lead_id: int) -> None:
    """Create or update mapping between a Telegram user and lead.

    Ensures that the `TgLink` entry reflects the specified `lead_id` for
    the given user and bot kind, refreshing the ``updated_at`` timestamp.
    """

    async with get_session() as s:
        current_lead = (
            await s.execute(
                select(TgLink.lead_id).where(
                    TgLink.user_id == user_id, TgLink.bot_kind == bot_kind
                )
            )
        ).scalar_one_or_none()

        if current_lead == lead_id:
            return

        stmt = (
            pg_insert(TgLink)
            .values(
                user_id=user_id,
                bot_kind=bot_kind,
                lead_id=lead_id,
                updated_at=now(),
            )
            .on_conflict_do_update(
                index_elements=[TgLink.user_id, TgLink.bot_kind],
                set_={"lead_id": lead_id, "updated_at": now()},
            )
        )
        await s.execute(stmt)
        await s.commit()


async def set_conversation(user_id: int, bot_kind: str, conversation_id: str) -> None:
    """Persist conversation identifier for a user and bot kind."""

    async with get_session() as s:
        await s.execute(
            update(TgLink)
            .where(TgLink.user_id == user_id, TgLink.bot_kind == bot_kind)
            .values(conversation_id=conversation_id, updated_at=now())
        )
        await s.commit()


async def get_by_lead(lead_id: int) -> list[TgLink]:
    """Return all chat links associated with the given lead."""

    async with get_session() as s:
        res = await s.execute(select(TgLink).where(TgLink.lead_id == lead_id))
        return list(res.scalars())


async def get_by_user(user_id: int, bot_kind: str) -> Optional[TgLink]:
    """Fetch chat link for a user and bot kind if present."""

    async with get_session() as s:
        return (await s.execute(
            select(TgLink).where(TgLink.user_id == user_id, TgLink.bot_kind == bot_kind)
        )).scalar_one_or_none()


async def get_by_conversation(conversation_id: str) -> list[TgLink]:
    """Return chat links sharing the specified conversation identifier."""

    async with get_session() as s:
        res = await s.execute(
            select(TgLink).where(TgLink.conversation_id == conversation_id)
        )
        return list(res.scalars())
