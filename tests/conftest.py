import os
import sys
import types
import pytest
import pytest_asyncio

# Ensure project root is on sys.path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# Map configuration and oauth modules that are missing in repo
import app.core.config as core_config
sys.modules.setdefault('app.config', core_config)

# Provide lightweight proxy for oauth2 to avoid heavy imports during test collection
oauth2_stub = types.ModuleType('app.oauth2')

async def _ensure_fresh_access(*args, **kwargs):
    from app.api.oauth2 import ensure_fresh_access as real
    return await real(*args, **kwargs)

async def _refresh_tokens(*args, **kwargs):
    from app.api.oauth2 import refresh_tokens as real
    return await real(*args, **kwargs)

oauth2_stub.ensure_fresh_access = _ensure_fresh_access
oauth2_stub.refresh_tokens = _refresh_tokens
sys.modules.setdefault('app.oauth2', oauth2_stub)

# Stub missing app.amochats module with async no-op functions
stub = types.ModuleType('app.amochats')
async def _noop(*args, **kwargs):
    return None
stub.send_text_from_manager = _noop
stub.ensure_chat_created = _noop
stub.send_text_from_client = _noop
sys.modules.setdefault('app.amochats', stub)

# Map dedup module used via deprecated import path
import app.services.dedup as dedup_module
sys.modules.setdefault('app.dedup', dedup_module)

# Map queue module for worker_rmq
import app.services.queue as queue_module
sys.modules.setdefault('app.queue', queue_module)

# Map amo_client for worker_rmq
import app.adapters.amo_client as amo_client_module
sys.modules.setdefault('app.amo_client', amo_client_module)

# Map logging_setup module
import app.core.logging_setup as logging_setup_module
sys.modules.setdefault('app.logging_setup', logging_setup_module)

# In-memory database fixture
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
import app.db.db as db_module
from app.db.db import Base


@pytest_asyncio.fixture
async def in_memory_db(monkeypatch):
    """Provide a fresh in-memory database for each test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(db_module, "engine", engine, raising=False)
    monkeypatch.setattr(db_module, "SessionLocal", SessionLocal, raising=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield
    finally:
        await engine.dispose()
