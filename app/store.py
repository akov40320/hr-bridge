from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.db import get_session
from app.models import LeadLink, Task


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


# --- Очередь задач синхронизации ------------------------------------------

async def enqueue_pending(task: dict[str, Any]) -> int | None:
    """
    Кладёт задачу в очередь (status=queued).
    task: произвольный payload, но обычно содержит platform/action/...
    Возвращает ID задачи (если нужно), иначе None.
    """
    async with get_session() as s:
        stmt = insert(Task).values(
            platform=task.get("platform", "unknown"),
            action=task.get("action", "unknown"),
            payload=task,
        ).returning(Task.id)
        res = await s.execute(stmt)
        await s.commit()
        row = res.first()
        return row[0] if row else None


async def fetch_and_lock(limit: int = 50) -> list[Task]:
    """
    Забирает пачку queued-задач с блокировкой (SKIP LOCKED),
    помечает их status=running и увеличивает attempts.
    """
    async with get_session() as s:
        q = (
            select(Task)
            .where(Task.status == "queued")
            .order_by(Task.id)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        rows = (await s.execute(q)).scalars().all()
        if not rows:
            return []

        ids = [r.id for r in rows]
        await s.execute(
            update(Task)
            .where(Task.id.in_(ids))
            .values(status="running", attempts=Task.attempts + 1)
        )
        await s.commit()
        return rows


async def mark_task_done(task_id: int) -> None:
    """
    Помечает задачу как выполненную.
    """
    async with get_session() as s:
        await s.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(status="done", error=None)
        )
        await s.commit()


async def mark_task_failed(task_id: int, err: str) -> None:
    """
    Помечает задачу как неуспешную с текстом ошибки.
    """
    async with get_session() as s:
        await s.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(status="failed", error=err)
        )
        await s.commit()
