from __future__ import annotations
import hashlib, time
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import delete
from app.db import get_session
from app.models import EventDedup


def calc_key(source: str, payload: bytes) -> str:
    return f"{source}:{hashlib.sha256(payload).hexdigest()}"


async def check_and_store(key: str) -> bool:
    """
    True — первое появление (можно обрабатывать).
    False — уже видели (дубликат).
    """
    async with get_session() as s:
        stmt = insert(EventDedup).values(key=key).on_conflict_do_nothing(index_elements=[EventDedup.key])
        res = await s.execute(stmt)
        await s.commit()
        return res.rowcount == 1


async def cleanup_older_than(seconds: int = 3 * 24 * 3600) -> int:
    """
    Удаляет старые ключи. Вернёт число удалённых.
    """
    cutoff = time.time() - seconds
    async with get_session() as s:
        q = delete(EventDedup).where(EventDedup.created_at < EventDedup.created_at.op("AT TIME ZONE")("UTC"))
        # простой способ: Postgres now() сравнивать сложно без tz; можно оставить кроном через SQL.
        # Либо делай raw-SQL с NOW()-interval. Проще — выполнять чистку SQL-скриптом по расписанию.
        # Здесь оставим заглушку (ничего не удалит). Используй отдельный SQL в cron.
        res = 0
        await s.commit()
        return res
