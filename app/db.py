import hashlib
import logging
import re
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.engine.url import make_url
from app.config import settings
import asyncio, asyncpg
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

log = logging.getLogger("dburl")




ASYNC_DSN = settings.DATABASE_URL


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
