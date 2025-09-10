from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import get_session
from app.db.models import LeadStatusTransition


async def get_last_transition(lead_id: int) -> Optional[LeadStatusTransition]:
    """Return last stored transition for a lead if present."""
    async with get_session() as s:
        return (
            await s.execute(
                select(LeadStatusTransition).where(LeadStatusTransition.lead_id == lead_id)
            )
        ).scalar_one_or_none()


async def set_last_transition(lead_id: int, status_id: int, ts: int) -> None:
    """Store the latest applied transition for a lead."""
    async with get_session() as s:
        stmt = (
            pg_insert(LeadStatusTransition)
            .values(lead_id=lead_id, status_id=status_id, ts=ts)
            .on_conflict_do_update(
                index_elements=[LeadStatusTransition.lead_id],
                set_={"status_id": status_id, "ts": ts},
            )
        )
        await s.execute(stmt)
        await s.commit()
