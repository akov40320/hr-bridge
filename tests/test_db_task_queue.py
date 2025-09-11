import pytest
from sqlalchemy import select, func

from app.services.db_task_queue import enqueue_task, process_next_task
from app.db import get_session
from app.db.models import Task


@pytest.mark.asyncio
async def test_enqueue_unique(in_memory_db):
    await enqueue_task("task1", "cand1", {"msg": "hello"})
    await enqueue_task("task1", "cand1", {"msg": "hello again"})
    async with get_session() as session:
        cnt = await session.scalar(select(func.count()).select_from(Task))
        assert cnt == 1


@pytest.mark.asyncio
async def test_process_next_task_success(in_memory_db):
    await enqueue_task("task1", "cand1", {"msg": "hi"})

    async def handler(payload):
        assert payload["msg"] == "hi"

    processed = await process_next_task(handler)
    assert processed is True
    async with get_session() as session:
        row = (await session.execute(select(Task).where(Task.task_id == "task1"))).scalar_one()
        assert row.status == "done"
        assert row.attempts == 0


@pytest.mark.asyncio
async def test_process_next_task_failure_keeps_pending(in_memory_db):
    await enqueue_task("task1", "cand1", {"msg": "boom"})

    async def handler(payload):
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        await process_next_task(handler)

    async with get_session() as session:
        row = (await session.execute(select(Task).where(Task.task_id == "task1"))).scalar_one()
        assert row.status == "pending"
        assert row.attempts == 1
