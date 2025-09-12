import pytest

from app.services import dedup


class DummySession:
    def __init__(self):
        self.params = None

    async def execute(self, q, params):
        self.params = params
        class Res:
            rowcount = 0
        return Res()

    async def commit(self):
        pass


class DummyContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        pass


@pytest.mark.asyncio
async def test_cleanup_older_than_passes_seconds_as_int(monkeypatch):
    session = DummySession()
    monkeypatch.setattr(dedup, "get_session", lambda: DummyContext(session))
    await dedup.cleanup_older_than(42)
    assert isinstance(session.params["sec"], int)
    assert session.params["sec"] == 42
