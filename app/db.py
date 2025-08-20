import hashlib
import logging
import re
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.engine.url import make_url
from app.config import settings
import asyncio, asyncpg


log = logging.getLogger("dburl")


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


def _mask(u: str) -> str:
    return re.sub(r'//([^:]+):[^@]+@', r'//\1:***@', u)


raw = settings.DATABASE_URL
ASYNC_DSN = _to_asyncpg_dsn(settings.DATABASE_URL)
log.warning("DATABASE_URL REPR: %r len=%d sha256=%s",
            raw, len(raw), hashlib.sha256(raw.encode()).hexdigest())
log.warning("DATABASE_URL MASK: %s", _mask(raw))
log.warning("ASYNC_DSN      : %s", _mask(ASYNC_DSN))

async def _probe():
    dsn = ASYNC_DSN.replace("postgresql+asyncpg", "postgresql")
    dsn = dsn.replace("ssl=require", "sslmode=require")
    conn = await asyncpg.connect(dsn)
    v = await conn.fetchval("select 1")
    print("PROBE_OK", v)
    await conn.close()

asyncio.get_event_loop().run_until_complete(_probe())

engine = create_async_engine(
    ASYNC_DSN,
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
    from app import models  # noqa: F401  (важно: регистрирует таблицы в Base.metadata)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine():
    await engine.dispose()
