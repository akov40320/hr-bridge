"""Utilities for deduplicating events."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Awaitable, Callable, cast

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult

from app.db import get_session
from app.db.models import EventDedup

logger = logging.getLogger(__name__)


def calc_key(source: str, payload: str | bytes) -> str:
    """Вернуть ключ дедупликации для полезной нагрузки события."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return f"{source}:{hashlib.sha256(payload).hexdigest()}"


async def check_and_store(key: str) -> bool:
    """Сохранить ключ, если его ещё нет, и вернуть, был ли он вставлен."""
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
    """Удалить записи дедупликации старше указанного количества секунд."""
    async with get_session() as s:
        q = text(
            "DELETE FROM events_dedup "
            "WHERE created_at < (NOW() AT TIME ZONE 'utc') - (:sec * INTERVAL '1 second')"
        )
        res = await s.execute(q, {"sec": seconds})
        await s.commit()
        return cast(CursorResult[Any], res).rowcount or 0


async def once(dedup_key: str, ttl: int, operation: Callable[[], Awaitable[Any]]) -> bool:
    """Выполнить ``operation`` один раз для ``dedup_key`` в пределах окна TTL.

    Ключ сохраняется через :func:`check_and_store`. Если ключ уже присутствует,
    операция пропускается и возвращается ``False``.

    Args:
        dedup_key: уникальный идентификатор операции.
        ttl: время жизни записи дедупликации в секундах.
        operation: корутина, которую нужно выполнить при новом ключе.

    Returns:
        ``True``, если операция была выполнена, иначе ``False``.
    """

    if not await check_and_store(dedup_key):
        logger.info("once: дубликат %s -> пропуск", dedup_key)
        return False
    await operation()
    return True
