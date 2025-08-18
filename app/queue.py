from __future__ import annotations
import json
import aio_pika
from app.config import settings

_conn = None
_chan = None
_exch = None


async def _ensure():
    global _conn, _chan, _exch
    if _conn and not _conn.is_closed:
        return
    _conn = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    _chan = await _conn.channel(publisher_confirms=True)
    await _chan.set_qos(prefetch_count=32)

    # exchange
    _exch = await _chan.declare_exchange(
        settings.RMQ_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
    )

    # DLQ (отдельная очередь без повторной доставки)
    await _chan.declare_queue(settings.RMQ_DLQ_QUEUE, durable=True)
    q_dlq = await _chan.get_queue(settings.RMQ_DLQ_QUEUE)
    await q_dlq.bind(_exch, routing_key="tasks.dlq")

    # main queue (БЕЗ DLX!)
    await _chan.declare_queue(settings.RMQ_TASK_QUEUE, durable=True)
    q_main = await _chan.get_queue(settings.RMQ_TASK_QUEUE)
    await q_main.bind(_exch, routing_key="tasks")

    # retry queue с TTL -> dead-letter в main
    await _chan.declare_queue(
        settings.RMQ_RETRY_QUEUE, durable=True,
        arguments={
            "x-message-ttl": settings.RMQ_RETRY_TTL_MS,
            "x-dead-letter-exchange": settings.RMQ_EXCHANGE,
            "x-dead-letter-routing-key": "tasks",
        }
    )


async def publish_task(payload: dict, attempts: int = 0):
    await _ensure()
    body = json.dumps({"payload": payload, "attempts": attempts}, ensure_ascii=False).encode("utf-8")
    msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
    await _exch.publish(msg, routing_key="tasks")


async def publish_retry(payload: dict, attempts: int):
    await _ensure()
    body = json.dumps({"payload": payload, "attempts": attempts}, ensure_ascii=False).encode("utf-8")
    msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
    # default exchange умеет роутить по имени очереди
    await _chan.default_exchange.publish(msg, routing_key=settings.RMQ_RETRY_QUEUE)


async def publish_dlq(payload: dict, attempts: int, error: str | None = None):
    await _ensure()
    obj = {"payload": payload, "attempts": attempts, "error": error}
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
    await _exch.publish(msg, routing_key="tasks.dlq")


async def consume(handler):
    """handler(dict_payload, attempts)->await"""
    await _ensure()
    q = await _chan.get_queue(settings.RMQ_TASK_QUEUE)
    async with q.iterator() as it:
        async for message in it:
            async with message.process(ignore_processed=True):
                # 1) защищённый парсинг
                try:
                    obj = json.loads(message.body.decode("utf-8"))
                    payload = obj.get("payload") or {}
                    attempts = int(obj.get("attempts") or 0)
                except Exception as e:
                    raw = message.body.decode("utf-8", "ignore")
                    await publish_dlq({"_raw": raw}, 0, f"json-parse: {e}")
                    continue


                try:
                    await handler(payload, attempts)
                except Exception as e:

                    await publish_dlq(payload, attempts, f"uncaught: {e}")

