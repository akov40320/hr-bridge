from __future__ import annotations
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool  # безопасно импортировать всегда

from app.core.config import get_settings

_engine: Optional[AsyncEngine] = None
_SessionLocal: Optional[async_sessionmaker[AsyncSession]] = None

# Флаги, нужные только для тестов (in-memory SQLite)
_SQLITE_MEMORY: bool = False
_TABLES_READY: bool = False


class Base(DeclarativeBase):
    pass


def _is_sqlite_memory_url(url: str) -> bool:
    # классическая форма и вариант через URI
    return url.startswith("sqlite+aiosqlite:///:memory:") or "file::memory:" in url


def get_engine() -> AsyncEngine:
    global _engine, _SQLITE_MEMORY
    if _engine is None:
        settings = get_settings()  # читаем ENV только при первом вызове
        url = settings.DATABASE_URL

        kwargs = dict(echo=False, pool_pre_ping=True)

        # Включаем StaticPool только для in-memory SQLite (тесты)
        if _is_sqlite_memory_url(url):
            _SQLITE_MEMORY = True
            kwargs.update({
                "poolclass": StaticPool,
            })

        _engine = create_async_engine(url, **kwargs)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _SessionLocal


async def _ensure_tables_created_once() -> None:
    """
    Создаём таблицы один раз, но ТОЛЬКО для in-memory SQLite (тесты).
    В проде (PostgreSQL) — используется Alembic, сюда не заходим.
    """
    global _TABLES_READY
    if _TABLES_READY or not _SQLITE_MEMORY:
        return
    from . import models  # noqa: F401 — регистрирует таблицы в Base.metadata
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _TABLES_READY = True


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    # Для тестов: перед первой сессией гарантируем наличие таблиц
    await _ensure_tables_created_once()

    SessionLocal = get_sessionmaker()
    async with SessionLocal() as s:
        yield s


async def init_db() -> None:
    """
    Только для dev/локального первого запуска.
    В проде — Alembic миграции.
    """
    from . import models  # noqa: F401 — регистрирует таблицы в Base.metadata
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    eng = get_engine()
    await eng.dispose()
