import json
import types
import pytest

from app.services import queue


@pytest.mark.asyncio
async def test_publish_task(monkeypatch):
    published = []

    class DummyExchange:
        async def publish(self, msg, routing_key):
            published.append((json.loads(msg.body.decode()), routing_key))

    dummy_exch = DummyExchange()

    class DummyChan:
        def __init__(self):
            self.default_exchange = DummyExchange()

    dummy_chan = DummyChan()

    async def fake_ensure():
        queue._exch = dummy_exch
        queue._chan = dummy_chan

    monkeypatch.setattr(queue, "_ensure", fake_ensure)

    await queue.publish_task({"foo": "bar"}, attempts=2)
    assert published == [({"payload": {"foo": "bar"}, "attempts": 2}, "tasks")]


@pytest.mark.asyncio
async def test_publish_retry(monkeypatch):
    published = []

    class DummyExchange:
        async def publish(self, msg, routing_key):
            published.append((json.loads(msg.body.decode()), routing_key))

    dummy_chan = types.SimpleNamespace(default_exchange=DummyExchange())

    async def fake_ensure():
        queue._chan = dummy_chan

    monkeypatch.setattr(queue, "_ensure", fake_ensure)

    await queue.publish_retry({"a": 1}, attempts=3)
    assert published == [({"payload": {"a": 1}, "attempts": 3}, queue.settings.RMQ_RETRY_QUEUE)]


@pytest.mark.asyncio
async def test_publish_dlq(monkeypatch):
    published = []

    class DummyExchange:
        async def publish(self, msg, routing_key):
            published.append((json.loads(msg.body.decode()), routing_key))

    dummy_exch = DummyExchange()

    async def fake_ensure():
        queue._exch = dummy_exch

    monkeypatch.setattr(queue, "_ensure", fake_ensure)

    await queue.publish_dlq({"a": 1}, attempts=4, error="boom")
    assert published == [({"payload": {"a": 1}, "attempts": 4, "error": "boom"}, "tasks.dlq")]
