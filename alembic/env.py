import asyncio
from logging.config import fileConfig
from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from app.core.config import settings
from app.db import Base  # важно: без подключений к БД!
from app.db import models  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

url = settings.DATABASE_URL
if not url:
    raise RuntimeError("DATABASE_URL не задан (ни в ENV, ни в .env).")


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    engine: AsyncEngine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online_sync() -> None:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        do_run_migrations(conn)


if context.is_offline_mode():
    run_migrations_offline()
else:
    if "+asyncpg" in url:
        asyncio.run(run_migrations_online_async())
    else:
        run_migrations_online_sync()
