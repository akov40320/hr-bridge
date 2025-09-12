"""Утилиты для удаления дубликатов событий."""

from __future__ import annotations

import hashlib
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult

from app.db import get_session
from app.db.models import EventDedup


def calc_key(source: str, payload: str | bytes) -> str:
    """Вернуть ключ дедупликации для полезной нагрузки события."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return f"{source}:{hashlib.sha256(payload).hexdigest()}"


async def check_and_store(key: str) -> bool:
    """Сохранить ключ, если его нет, и вернуть, был ли он вставлен."""
    async with get_session() as s:
        stmt = (
            insert(EventDedup)
            .values(key=key)
            .on_conflict_do_nothing(index_elements=[EventDedup.key])
        )
        res = await s.execute(stmt)
        await s.commit()
        return cast(CursorResult[Any], res).rowcount == 1


async def cleanup_older_than(seconds: int = 72 * 3600) -> int:
    """Удалить записи дедупликации, старше указанного количества секунд."""
    async with get_session() as s:
        q = text(
            "DELETE FROM events_dedup WHERE created_at < (NOW() AT TIME ZONE 'utc') - "
            "make_interval(secs => :sec)"
        )
        res = await s.execute(q, {"sec": seconds})
        await s.commit()
        return cast(CursorResult[Any], res).rowcount or 0
