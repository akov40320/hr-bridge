import os
import sys
import types
import importlib
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

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


@pytest.fixture
def app(monkeypatch):
    """FastAPI application with essential routers for tests."""
    from app.api import hh_incoming

    application = FastAPI()

    class DummyAmoClient:
        @classmethod
        async def create(cls, http_client):
            return object()

    monkeypatch.setattr(hh_incoming, "AmoClient", DummyAmoClient, raising=False)
    application.include_router(hh_incoming.router)
    return application


@pytest.fixture
def client(app):
    """Synchronous test client for FastAPI app."""
    return TestClient(app)


@pytest.fixture
def queue_mock(monkeypatch):
    """Capture tasks published to the queue."""
    published: list = []

    async def fake_publish(payload, *args, **kwargs):
        published.append(payload)

    modules = [
        "app.services.queue",
        "app.services.lead_processor",
        "app.services.survey",
        "app.services.survey_service",
        "app.tg_router",
    ]
    for mod_name in modules:
        try:
            mod = importlib.import_module(mod_name)
            client = getattr(mod, "rabbitmq", None)
            if client and hasattr(client, "publish_task"):
                monkeypatch.setattr(client, "publish_task", fake_publish, raising=False)
        except Exception:
            pass

    return published


@pytest.fixture
def token_mock(monkeypatch):
    """Mock OAuth token retrieval."""
    async def fake_ensure_fresh_access(**kwargs):
        return "token"

    async def fake_refresh_tokens(*args, **kwargs):
        return {"access_token": "token"}

    modules = [
        "app.oauth2",
        "app.adapters.hh",
        "app.adapters.avito",
    ]
    for mod_name in modules:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "ensure_fresh_access"):
                monkeypatch.setattr(mod, "ensure_fresh_access", fake_ensure_fresh_access, raising=False)
            if mod_name == "app.oauth2" and hasattr(mod, "refresh_tokens"):
                monkeypatch.setattr(mod, "refresh_tokens", fake_refresh_tokens, raising=False)
        except Exception:
            pass

    return "token"
