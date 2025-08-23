from __future__ import annotations
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
import asyncio

from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, create_async_engine, async_sessionmaker
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

_engine: Optional[AsyncEngine] = None
_SessionLocal: Optional[async_sessionmaker[AsyncSession]] = None

# ---- только для in-memory sqlite в тестах ----
_SQLITE_MEMORY: bool = False
_TABLES_READY: bool = False
_LOOP_ID: Optional[int] = None
# ---------------------------------------------

class Base(DeclarativeBase):
    pass


def _is_sqlite_memory_url(url: str) -> bool:
    return url.startswith("sqlite+aiosqlite:///:memory:") or "file::memory:" in url


def get_engine() -> AsyncEngine:
    global _engine, _SQLITE_MEMORY
    if _engine is None:
        s = get_settings()
        url = s.DATABASE_URL
        kwargs = dict(echo=False, pool_pre_ping=True)
        if _is_sqlite_memory_url(url):
            _SQLITE_MEMORY = True
            kwargs.update(
                poolclass=StaticPool,
                # connect_args={"check_same_thread": False},  # не обязательно для aiosqlite
            )
        _engine = create_async_engine(url, **kwargs)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _SessionLocal


async def _ensure_tables_created_once() -> None:
    """Для sqlite :memory: — создаём чистую схему на каждый новый event loop (каждый тест)."""
    global _TABLES_READY, _LOOP_ID

    if not _SQLITE_MEMORY:
        # не тестовый ин-мемори — ничего не делаем
        return

    loop_id = id(asyncio.get_running_loop())

    # новый тест (новый event loop) → снести и пересоздать схему
    if _LOOP_ID != loop_id:
        from . import models  # noqa: F401
        async with get_engine().begin() as conn:
            # если схемы не было — drop_all просто ничего не сделает
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        _TABLES_READY = True
        _LOOP_ID = loop_id
        return

    # тот же тест, но ещё не создавали таблицы
    if not _TABLES_READY:
        from . import models  # noqa: F401
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _TABLES_READY = True


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    # важно: сначала инициализируем движок (определится _SQLITE_MEMORY), затем — схема
    get_engine()
    await _ensure_tables_created_once()

    SessionLocal = get_sessionmaker()
    async with SessionLocal() as s:
        yield s


async def init_db() -> None:
    """Только для dev/локального. В проде — Alembic."""
    from . import models  # noqa: F401
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Полный сброс глобалов — пригодится фикстурам."""
    global _engine, _SessionLocal, _TABLES_READY, _SQLITE_MEMORY, _LOOP_ID
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _SessionLocal = None
    _TABLES_READY = False
    _SQLITE_MEMORY = False
    _LOOP_ID = None
