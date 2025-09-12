"""Вспомогательные функции для хранения связей сделок с внешними ресурсами."""

from __future__ import annotations
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.db import get_session
from app.db.models import LeadLink


async def save_link(
    *,
    lead_id: int,
    platform: str,
    owner_id: Optional[str],
    vacancy_id: str,
    external_id: Optional[str],
) -> None:
    """
    Upsert связи lead ↔ внешний объект (HH/Avito), с учётом owner_id (employer_id/account_id).
    """
    async with get_session() as s:
        values = {
            "lead_id": lead_id,
            "platform": platform,
            "owner_id": owner_id,
            "vacancy_id": vacancy_id,
            "external_id": external_id,
        }

        existing = (
            await s.execute(select(LeadLink).where(LeadLink.lead_id == lead_id))
        ).scalar_one_or_none()

        if existing:
            update_fields = {
                key: value
                for key, value in values.items()
                if getattr(existing, key) != value
            }
            if not update_fields:
                return
            stmt = (
                insert(LeadLink)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[LeadLink.lead_id],
                    set_=update_fields,
                )
            )
        else:
            stmt = insert(LeadLink).values(**values)

        await s.execute(stmt)
        await s.commit()


async def find_link(lead_id: int) -> Optional[dict[str, Any]]:
    """Вернуть данные связи для сделки, если они существуют."""
    async with get_session() as s:
        row = (
            await s.execute(select(LeadLink).where(LeadLink.lead_id == lead_id))
        ).scalar_one_or_none()
        if not row:
            return None
        return {
            "lead_id": row.lead_id,
            "platform": row.platform,
            "owner_id": row.owner_id,          # <- ключ для выбора токена
            "vacancy_id": row.vacancy_id,
            "external_id": row.external_id,
        }
