import json
import types
import asyncio
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


@pytest.mark.asyncio
async def test_consume_catches_unexpected_exception(monkeypatch):
    acked = False
    dlq_calls = []

    class DummyMessage:
        body = json.dumps({"payload": {"foo": "bar"}, "attempts": 0}).encode()

        async def ack(self):
            nonlocal acked
            acked = True

    class DummyIterator:
        def __init__(self, message):
            self._message = message
            self._yielded = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._yielded:
                raise asyncio.CancelledError
            self._yielded = True
            return self._message

    class DummyQueue:
        def __init__(self, message):
            self._message = message

        def iterator(self):
            return DummyIterator(self._message)

    class DummyChannel:
        is_closed = False

        async def get_queue(self, name):
            return DummyQueue(DummyMessage())

    client = RabbitMQClient()

    async def fake_ensure():
        client._conn = types.SimpleNamespace(is_closed=False)
        client._chan = DummyChannel()

    async def fake_dlq(payload, attempts, error=None):
        dlq_calls.append((payload, attempts, error))

    monkeypatch.setattr(client, "_ensure", fake_ensure)
    monkeypatch.setattr(client, "publish_dlq", fake_dlq)

    async def handler(payload):
        raise ValueError("boom")

    await client.consume(handler, max_attempts=1)

    assert acked
    assert dlq_calls == [({"foo": "bar"}, 1, "boom")]

