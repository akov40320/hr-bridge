from __future__ import annotations
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

_engine: Optional[AsyncEngine] = None
_SessionLocal: Optional[async_sessionmaker[AsyncSession]] = None


class Base(DeclarativeBase):
    pass


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()  # ← читаем ENV только при первом вызове
        _engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _SessionLocal


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
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
