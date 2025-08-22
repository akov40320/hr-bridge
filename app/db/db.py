from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


@asynccontextmanager
async def get_session():
    async with SessionLocal() as s:
        yield s


async def init_db():
    """
    Только для dev/локального первого запуска.
    В проде использовать Alembic миграции.
    """
    from . import models  # noqa: F401  (важно: регистрирует таблицы в Base.metadata)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine():
    await engine.dispose()
