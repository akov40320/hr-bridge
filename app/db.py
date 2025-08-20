from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.engine.url import make_url
from app.config import settings


def _to_asyncpg_dsn(dsn: str) -> str:
    """
    Если пришёл postgresql://... → превратим в postgresql+asyncpg://...
    Если уже asyncpg — оставляем как есть.
    """
    u = make_url(dsn)
    backend = u.get_backend_name()  # 'postgresql' | 'sqlite' ...
    driver = u.get_driver_name() or ""  # 'psycopg2' | 'asyncpg' | ''
    if backend in ("postgresql", "postgres") and "asyncpg" not in driver:
        u = u.set(drivername="postgresql+asyncpg")
    return str(u)


ASYNC_DSN = _to_asyncpg_dsn(settings.DATABASE_URL)

engine = create_async_engine(
    ASYNC_DSN,
    echo=False,  # при необходимости сделай это настройкой
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
    from app import models  # noqa: F401  (важно: регистрирует таблицы в Base.metadata)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine():
    await engine.dispose()
