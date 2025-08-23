"""Utilities for deduplicating events."""

from __future__ import annotations

import hashlib
from typing import Any, cast 

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult

from app.db import get_session
from app.db.models import EventDedup


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
