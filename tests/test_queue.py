import json
import types
import pytest

from app.core.config import get_settings
from app.services.queue import RabbitMQClient

settings = get_settings()

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

    client = RabbitMQClient()

    async def fake_ensure():
        client._exch = dummy_exch
        client._chan = DummyChan()

    monkeypatch.setattr(client, "_ensure", fake_ensure)

    await client.publish_task({"foo": "bar"}, attempts=2)
    assert published == [({"payload": {"foo": "bar"}, "attempts": 2}, "tasks")]


@pytest.mark.asyncio
async def test_publish_retry(monkeypatch):
    published = []

    class DummyExchange:
        async def publish(self, msg, routing_key):
            published.append((json.loads(msg.body.decode()), routing_key))

    dummy_chan = types.SimpleNamespace(default_exchange=DummyExchange())
    client = RabbitMQClient()

    async def fake_ensure():
        client._chan = dummy_chan

    monkeypatch.setattr(client, "_ensure", fake_ensure)

    await client.publish_retry({"a": 1}, attempts=3)
    assert published == [({"payload": {"a": 1}, "attempts": 3}, settings.RMQ_RETRY_QUEUE)]


@pytest.mark.asyncio
async def test_publish_dlq(monkeypatch):
    published = []

    class DummyExchange:
        async def publish(self, msg, routing_key):
            published.append((json.loads(msg.body.decode()), routing_key))

    dummy_exch = DummyExchange()
    client = RabbitMQClient()

    async def fake_ensure():
        client._exch = dummy_exch

    monkeypatch.setattr(client, "_ensure", fake_ensure)

    await client.publish_dlq({"a": 1}, attempts=4, error="boom")
    assert published == [({"payload": {"a": 1}, "attempts": 4, "error": "boom"}, "tasks.dlq")]

