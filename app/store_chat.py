from typing import Optional
from sqlalchemy import select, update, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.db import get_session
from app.models import TgLink


async def upsert_tg_link(user_id: int, bot_kind: str, lead_id: int) -> None:
    async with get_session() as s:
        stmt = (
            pg_insert(TgLink)
            .values(user_id=user_id, bot_kind=bot_kind, lead_id=lead_id, updated_at=func.now())
            .on_conflict_do_update(
                index_elements=[TgLink.user_id, TgLink.bot_kind],
                set_={"lead_id": lead_id, "updated_at": func.now()}
            )
        )
        await s.execute(stmt)
        await s.commit()


async def set_conversation(user_id: int, bot_kind: str, conversation_id: str) -> None:
    async with get_session() as s:
        await s.execute(
            update(TgLink)
            .where(TgLink.user_id == user_id, TgLink.bot_kind == bot_kind)
            .values(conversation_id=conversation_id, updated_at=func.now())
        )
        await s.commit()


async def get_by_lead(lead_id: int) -> list[TgLink]:
    async with get_session() as s:
        return (await s.execute(
            select(TgLink).where(TgLink.lead_id == lead_id)
        )).scalars().all()


async def get_by_user(user_id: int, bot_kind: str) -> Optional[TgLink]:
    async with get_session() as s:
        return (await s.execute(
            select(TgLink).where(TgLink.user_id == user_id, TgLink.bot_kind == bot_kind)
        )).scalar_one_or_none()


async def get_by_conversation(conversation_id: str) -> list[TgLink]:
    async with get_session() as s:
        return (await s.execute(
            select(TgLink).where(TgLink.conversation_id == conversation_id)
        )).scalars().all()
