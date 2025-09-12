"""Очередь задач на базе БД, обеспечивающая идемпотентную обработку."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db import get_session
from app.db.models import Task


async def enqueue_task(task_id: str, candidate_id: str, payload: Dict[str, Any]) -> Task:
    """Вставить новую задачу, если она отсутствует, и вернуть её."""
    async with get_session() as session:
        stmt = (
            insert(Task)
            .values(task_id=task_id, candidate_id=candidate_id, payload=payload)
            .on_conflict_do_nothing(index_elements=[Task.task_id])
        )
        await session.execute(stmt)
        await session.commit()

    async with get_session() as session:
        return (
            await session.execute(select(Task).where(Task.task_id == task_id))
        ).scalar_one()


async def process_next_task(handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> bool:
    """Извлечь следующую ожидающую задачу и обработать её с помощью ``handler``.

    Возвращает ``True``, если задача была обработана, иначе ``False``.
    Если ``handler`` возбуждает исключение, задача возвращается в состояние
    ``pending``, а исключение пробрасывается дальше.
    """
    async with get_session() as session:
        row = (
            await session.execute(
                select(Task)
                .where(Task.status == "pending")
                .order_by(Task.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            await session.commit()
            return False
        try:
            await handler(row.payload)
        except Exception:  # pylint: disable=broad-except
            row.attempts += 1
            row.status = "pending"
            await session.commit()
            raise
        row.status = "done"
        await session.commit()
        return True
