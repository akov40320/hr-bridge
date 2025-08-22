import json
import logging
from typing import Any, Awaitable, Callable

import aio_pika

from app.core.config import settings


logger = logging.getLogger(__name__)


Handler = Callable[[dict, int], Awaitable[Any]]


class RMQ:
    def __init__(self) -> None:
        self._conn: aio_pika.RobustConnection | None = None
        self._chan: aio_pika.RobustChannel | None = None
        self._exch: aio_pika.Exchange | None = None

    async def _ensure(self) -> None:
        if self._conn and not self._conn.is_closed:
            return

        self._conn = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        self._chan = await self._conn.channel(publisher_confirms=True)
        await self._chan.set_qos(prefetch_count=settings.RMQ_PREFETCH)

        self._exch = await self._chan.declare_exchange(
            settings.RMQ_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )

        await self._chan.declare_queue(settings.RMQ_TASK_QUEUE, durable=True)
        await self._chan.declare_queue(
            settings.RMQ_RETRY_QUEUE,
            durable=True,
            arguments={
                "x-message-ttl": settings.RMQ_RETRY_TTL_MS,
                "x-dead-letter-exchange": settings.RMQ_EXCHANGE,
                "x-dead-letter-routing-key": "tasks",
            },
        )
        await self._chan.declare_queue(settings.RMQ_DLQ_QUEUE, durable=True)

        q_main = await self._chan.get_queue(settings.RMQ_TASK_QUEUE)
        await q_main.bind(self._exch, routing_key="tasks")

        q_dlq = await self._chan.get_queue(settings.RMQ_DLQ_QUEUE)
        await q_dlq.bind(self._exch, routing_key="tasks.dlq")

    async def close(self) -> None:
        if self._chan and not self._chan.is_closed:
            await self._chan.close()
        if self._conn and not self._conn.is_closed:
            await self._conn.close()
        self._conn = self._chan = self._exch = None

    async def publish_task(self, payload: dict, attempts: int = 0) -> None:
        await self._ensure()
        body = json.dumps({"payload": payload, "attempts": attempts}, ensure_ascii=False).encode()
        msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
        assert self._exch
        await self._exch.publish(msg, routing_key="tasks")

    async def publish_retry(self, payload: dict, attempts: int) -> None:
        await self._ensure()
        body = json.dumps({"payload": payload, "attempts": attempts}, ensure_ascii=False).encode()
        msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
        assert self._chan
        await self._chan.default_exchange.publish(msg, routing_key=settings.RMQ_RETRY_QUEUE)

    async def publish_dlq(self, payload: dict, attempts: int, error: str | None = None) -> None:
        await self._ensure()
        obj = {"payload": payload, "attempts": attempts, "error": error}
        body = json.dumps(obj, ensure_ascii=False).encode()
        msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
        assert self._exch
        await self._exch.publish(msg, routing_key="tasks.dlq")

    async def consume(self, handler: Handler, max_attempts: int = 10) -> None:
        await self._ensure()
        assert self._chan
        q = await self._chan.get_queue(settings.RMQ_TASK_QUEUE)
        async with q.iterator() as it:
            async for message in it:
                obj: dict[str, Any] | None = None
                attempts = 0
                payload: dict = {}
                try:
                    obj = json.loads(message.body.decode("utf-8"))
                    payload = obj.get("payload") or {}
                    try:
                        attempts = int(obj.get("attempts") or 0)
                    except Exception:
                        attempts = 0

                    await handler(payload, attempts)
                    await message.ack()

                except Exception as e:  # noqa: BLE001
                    await message.ack()
                    try:
                        cur_attempts = attempts + 1
                        if cur_attempts >= max_attempts:
                            await self.publish_dlq(payload, cur_attempts, str(e))
                            logger.exception("sent to DLQ after attempts=%s", cur_attempts)
                        else:
                            await self.publish_retry(payload, cur_attempts)
                            logger.exception(
                                "requeued to retry, attempt=%s", cur_attempts
                            )
                    except Exception:  # noqa: BLE001
                        logger.exception("failed to republish to retry/DLQ")


rmq = RMQ()

__all__ = ["rmq", "RMQ"]

