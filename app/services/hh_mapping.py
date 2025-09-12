"""Утилиты для сохранения и получения сопоставлений статусов HeadHunter.

Сопоставления хранятся в таблице БД ``hh_mapping`` и дублируются в
кэше в памяти для быстрого доступа. Кэш имеет простой TTL, чтобы избегать
частых обращений к базе данных.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from sqlalchemy import delete, insert, select

from app.db.db import get_session
from app.db.models import HhMapping

# Настройки кэша
_CACHE_TTL = 60  # секунд
_cache: dict[str, str] = {}
_cache_expire: float = 0
_lock = asyncio.Lock()


async def load() -> dict[str, str]:
    """Загрузить сопоставления из базы данных и обновить кэш."""

    async with get_session() as s:
        rows = (await s.execute(select(HhMapping))).scalars().all()
    mapping = {str(row.amo_status_id): row.hh_code for row in rows}

    async with _lock:
        global _cache_expire  # pylint: disable=global-statement
        _cache.clear()
        _cache.update(mapping)
        _cache_expire = time.time() + _CACHE_TTL
    return mapping


async def get(status_id: int) -> Optional[str]:
    """Вернуть значение сопоставления для ``status_id``, если оно есть."""

    async with _lock:
        if _cache and time.time() < _cache_expire:
            return _cache.get(str(status_id))

    mapping = await load()
    return mapping.get(str(status_id))


async def set_all(mapping: dict[str, str]) -> dict[str, str]:
    """Заменить сопоставление в базе данных и обновить кэш."""

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
        global _cache_expire  # pylint: disable=global-statement
        _cache.clear()
        _cache.update(mapping)
        _cache_expire = time.time() + _CACHE_TTL
    return mapping


__all__ = ["load", "get", "set_all"]
