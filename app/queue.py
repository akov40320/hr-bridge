import json, os
import aio_pika
import logging
from app.config import settings

logger = logging.getLogger(__name__)
_conn = _chan = _exch = None

def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

RMQ_PREFETCH = _int("RMQ_PREFETCH", 32)

async def _ensure():
    global _conn, _chan, _exch
    if _conn and not _conn.is_closed:
        return
    _conn = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    _chan = await _conn.channel(publisher_confirms=True)
    await _chan.set_qos(prefetch_count=RMQ_PREFETCH)

    _exch = await _chan.declare_exchange(settings.RMQ_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)

    await _chan.declare_queue(settings.RMQ_TASK_QUEUE, durable=True)
    await _chan.declare_queue(
        settings.RMQ_RETRY_QUEUE,
        durable=True,
        arguments={
            "x-message-ttl": settings.RMQ_RETRY_TTL_MS,
            "x-dead-letter-exchange": settings.RMQ_EXCHANGE,
            "x-dead-letter-routing-key": "tasks",
        },
    )
    await _chan.declare_queue(settings.RMQ_DLQ_QUEUE, durable=True)

    q_main = await _chan.get_queue(settings.RMQ_TASK_QUEUE)
    await q_main.bind(_exch, routing_key="tasks")

    q_dlq = await _chan.get_queue(settings.RMQ_DLQ_QUEUE)
    await q_dlq.bind(_exch, routing_key="tasks.dlq")

async def publish_task(payload: dict, attempts: int = 0):
    await _ensure()
    body = json.dumps({"payload": payload, "attempts": attempts}, ensure_ascii=False).encode()
    msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
    await _exch.publish(msg, routing_key="tasks")

async def publish_retry(payload: dict, attempts: int):
    await _ensure()
    body = json.dumps({"payload": payload, "attempts": attempts}, ensure_ascii=False).encode()
    msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
    await _chan.default_exchange.publish(msg, routing_key=settings.RMQ_RETRY_QUEUE)

async def publish_dlq(payload: dict, attempts: int, error: str | None = None):
    await _ensure()
    obj = {"payload": payload, "attempts": attempts, "error": error}
    body = json.dumps(obj, ensure_ascii=False).encode()
    msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
    await _exch.publish(msg, routing_key="tasks.dlq")

async def consume(handler):
    await _ensure()
    q = await _chan.get_queue(settings.RMQ_TASK_QUEUE)
    async with q.iterator() as it:
        async for message in it:
            try:
                obj = json.loads(message.body.decode("utf-8"))
                payload = obj.get("payload") or {}
                attempts = int(obj.get("attempts") or 0)
                await handler(payload, attempts)
                await message.ack()
            except Exception:
                logger.exception("consume handler crash; requeue")
                await message.nack(requeue=True)
