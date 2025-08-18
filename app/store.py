from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db import get_session
from app.models import LeadLink


# --- Привязка сделки к внешнему объекту (HH/Avito) -------------------------

async def save_link(
    lead_id: int,
    platform: str,
    vacancy_id: str,
    external_id: Optional[str],
) -> None:
    """
    Upsert связи lead ↔ внешний отклик (response_id/negotiation_id).
    """
    async with get_session() as s:
        stmt = (
            insert(LeadLink)
            .values(
                lead_id=lead_id,
                platform=platform,
                vacancy_id=vacancy_id,
                external_id=external_id,
            )
            .on_conflict_do_update(
                index_elements=[LeadLink.lead_id],
                set_={
                    "platform": platform,
                    "vacancy_id": vacancy_id,
                    "external_id": external_id,
                },
            )
        )
        await s.execute(stmt)
        await s.commit()


async def find_link(lead_id: int) -> Optional[dict[str, Any]]:
    """
    Достаёт связь по lead_id. Возвращает словарь или None.
    """
    async with get_session() as s:
        row = (
            await s.execute(
                select(LeadLink).where(LeadLink.lead_id == lead_id)
            )
        ).scalar_one_or_none()

        if not row:
            return None

        return {
            "lead_id": row.lead_id,
            "platform": row.platform,
            "vacancy_id": row.vacancy_id,
            "external_id": row.external_id,
        }
