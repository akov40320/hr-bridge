"""Database utilities for asynchronous SQLAlchemy engine and sessions."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from .base import Base


@dataclass
class _DBState:
    """Holds cached DB engine/sessionmaker and SQLite test flags."""

    engine: Optional[AsyncEngine] = None
    session_maker: Optional[async_sessionmaker[AsyncSession]] = None
    sqlite_memory: bool = False
    tables_ready: bool = False
    loop_id: Optional[int] = None


_STATE = _DBState()


def _is_sqlite_memory_url(url: str) -> bool:
    """Return ``True`` if the URL points to an in-memory SQLite database."""

    return url.startswith("sqlite+aiosqlite:///:memory:") or "file::memory:" in url


def get_engine() -> AsyncEngine:
    """Return a cached :class:`~sqlalchemy.ext.asyncio.AsyncEngine` instance."""

    if _STATE.engine is None:
        settings = get_settings()
        url = settings.DATABASE_URL.get_secret_value()
        kwargs: dict[str, object] = {"echo": False, "pool_pre_ping": True}
        if _is_sqlite_memory_url(url):
            _STATE.sqlite_memory = True
            kwargs["poolclass"] = StaticPool
        _STATE.engine = create_async_engine(url, **kwargs)
    return _STATE.engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return a cached async session factory."""

    if _STATE.session_maker is None:
        _STATE.session_maker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _STATE.session_maker


async def _ensure_tables_created_once() -> None:
    """Create tables for in-memory SQLite on each new event loop."""

    if not _STATE.sqlite_memory:
        # не тестовый ин-мемори — ничего не делаем
        return

    loop_id = id(asyncio.get_running_loop())

    # новый тест (новый event loop) → снести и пересоздать схему
    if _STATE.loop_id != loop_id:
        from . import models  # pylint: disable=unused-import, import-outside-toplevel

        async with get_engine().begin() as conn:
            # если схемы не было — drop_all просто ничего не сделает
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        _STATE.tables_ready = True
        _STATE.loop_id = loop_id
        return

    # тот же тест, но ещё не создавали таблицы
    if not _STATE.tables_ready:
        from . import models  # pylint: disable=unused-import, import-outside-toplevel

        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _STATE.tables_ready = True


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Provide a single :class:`AsyncSession` instance."""

    # важно: сначала инициализируем движок (определится _SQLITE_MEMORY), затем — схема
    get_engine()
    await _ensure_tables_created_once()

    session_local = get_sessionmaker()
    async with session_local() as session:
        yield session


async def init_db() -> None:
    """Initialize database schema (development only; production uses Alembic)."""

    from . import models  # pylint: disable=unused-import, import-outside-toplevel

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Reset cached state and dispose the engine (used in tests)."""

    if _STATE.engine is not None:
        await _STATE.engine.dispose()
    _STATE.engine = None
    _STATE.session_maker = None
    _STATE.tables_ready = False
    _STATE.sqlite_memory = False
    _STATE.loop_id = None
