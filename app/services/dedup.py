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
    """Return deduplication key for an event payload."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return f"{source}:{hashlib.sha256(payload).hexdigest()}"


async def check_and_store(key: str) -> bool:
    """Store the key if it's not present and return whether it was inserted."""
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
    """Remove deduplication entries older than the given number of seconds."""
    async with get_session() as s:
        q = text(
            "DELETE FROM events_dedup WHERE created_at < (NOW() AT TIME ZONE 'utc') - "
            "(:sec || ' seconds')::interval"
        )
        res = await s.execute(q, {"sec": seconds})
        await s.commit()
        return cast(CursorResult[Any], res).rowcount or 0


async def once(dedup_key: str, ttl: int, operation: Callable[[], Awaitable[Any]]) -> bool:
    """Run ``operation`` once for ``dedup_key`` within a TTL window.

    The key is stored using :func:`check_and_store`.  If the key was already
    present, the operation is skipped and ``False`` is returned.

    Args:
        dedup_key: Unique identifier for the operation.
        ttl: Time-to-live for deduplication entries, in seconds.
        operation: Coroutine function to execute when the key is new.

    Returns:
        ``True`` if the operation was executed, ``False`` otherwise.
    """

    if not await check_and_store(dedup_key):
        logger.info("once: duplicate %s -> skip", dedup_key)
        return False
    await operation()
    return True
