"""Utilities for storing and retrieving HeadHunter status mappings.

The mappings are stored in the ``hh_mapping`` database table and mirrored in
an in-memory cache for fast access.  The cache has a simple TTL to avoid
frequent database hits.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from sqlalchemy import delete, insert, select

from app.db.db import get_session
from app.db.models import HhMapping

# Cache settings
_CACHE_TTL = 60  # seconds
_cache: dict[str, str] = {}
_cache_expire: float = 0
_lock = asyncio.Lock()


async def load() -> dict[str, str]:
    """Load mappings from the database and refresh the cache."""

    async with get_session() as s:
        rows = (await s.execute(select(HhMapping))).scalars().all()
    mapping = {str(row.amo_status_id): row.hh_code for row in rows}

    async with _lock:
        global _cache_expire
        _cache.clear()
        _cache.update(mapping)
        _cache_expire = time.time() + _CACHE_TTL
    return mapping


async def get(status_id: int) -> Optional[str]:
    """Return the mapped value for ``status_id`` if present."""

    async with _lock:
        if _cache and time.time() < _cache_expire:
            return _cache.get(str(status_id))

    mapping = await load()
    return mapping.get(str(status_id))


async def set_all(mapping: dict[str, str]) -> dict[str, str]:
    """Replace mapping in the database and refresh the cache."""

    async with get_session() as s:
        await s.execute(delete(HhMapping))
        if mapping:
            rows = [
                {"amo_status_id": int(k), "hh_code": v}
                for k, v in mapping.items()
            ]
            await s.execute(insert(HhMapping), rows)
        await s.commit()

    async with _lock:
        global _cache_expire
        _cache.clear()
        _cache.update(mapping)
        _cache_expire = time.time() + _CACHE_TTL
    return mapping


__all__ = ["load", "get", "set_all"]

