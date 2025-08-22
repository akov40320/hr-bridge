import json, os
import asyncio
import aio_pika
import logging
from aio_pika import exceptions as aio_exc
from app.core.config import settings

logger = logging.getLogger(__name__)
_conn = _chan = _exch = None


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


RMQ_PREFETCH = _int("RMQ_PREFETCH", 32)


async def _ensure() -> None:
    global _conn, _chan, _exch
    if _conn and not _conn.is_closed and _chan and not _chan.is_closed:
        return

    _conn = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    _chan = await _conn.channel(publisher_confirms=True)
    await _chan.set_qos(prefetch_count=RMQ_PREFETCH)

    _exch = await _chan.declare_exchange(
        settings.RMQ_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
    )

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


async def connect() -> None:
    await _ensure()


async def close() -> None:
    global _conn, _chan, _exch
    try:
        if _chan and not _chan.is_closed:
            await _chan.close()
    finally:
        if _conn and not _conn.is_closed:
            await _conn.close()
    _conn = _chan = _exch = None


async def publish_task(payload: dict, attempts: int = 0) -> None:
    if not _conn or _conn.is_closed or not _chan or _chan.is_closed:
        await _ensure()
    body = json.dumps({"payload": payload, "attempts": attempts}, ensure_ascii=False).encode()
    msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
    try:
        await _exch.publish(msg, routing_key="tasks")
    except aio_exc.AMQPError:
        await _ensure()
        await _exch.publish(msg, routing_key="tasks")


async def publish_retry(payload: dict, attempts: int) -> None:
    if not _conn or _conn.is_closed or not _chan or _chan.is_closed:
        await _ensure()
    body = json.dumps({"payload": payload, "attempts": attempts}, ensure_ascii=False).encode()
    msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
    try:
        await _chan.default_exchange.publish(msg, routing_key=settings.RMQ_RETRY_QUEUE)
    except aio_exc.AMQPError:
        await _ensure()
        await _chan.default_exchange.publish(msg, routing_key=settings.RMQ_RETRY_QUEUE)


async def publish_dlq(payload: dict, attempts: int, error: str | None = None) -> None:
    if not _conn or _conn.is_closed or not _chan or _chan.is_closed:
        await _ensure()
    obj = {"payload": payload, "attempts": attempts, "error": error}
    body = json.dumps(obj, ensure_ascii=False).encode()
    msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
    try:
        await _exch.publish(msg, routing_key="tasks.dlq")
    except aio_exc.AMQPError:
        await _ensure()
        await _exch.publish(msg, routing_key="tasks.dlq")


async def consume(handler, max_attempts: int = 10):
    if not _conn or _conn.is_closed or not _chan or _chan.is_closed:
        await _ensure()
    while True:
        try:
            q = await _chan.get_queue(settings.RMQ_TASK_QUEUE)
            async with q.iterator() as it:
                async for message in it:
                    obj = None
                    attempts = 0
                    payload = {}
                    try:
                        obj = json.loads(message.body.decode("utf-8"))
                        payload = obj.get("payload") or {}
                        try:
                            attempts = int(obj.get("attempts") or 0)
                        except Exception:
                            attempts = 0

                        # запустим обработчик
                        await handler(payload, attempts)

                        # успех
                        await message.ack()

                    except Exception as e:
                        # не оставляем в очереди — ACK и перекидываем в retry/DLQ
                        await message.ack()
                        try:
                            cur_attempts = attempts + 1
                            if cur_attempts >= max_attempts:
                                await publish_dlq(payload, cur_attempts, str(e))
                                logger.exception("sent to DLQ after attempts=%s", cur_attempts)
                            else:
                                await publish_retry(payload, cur_attempts)
                                logger.exception("requeued to retry, attempt=%s", cur_attempts)
                        except Exception:
                            logger.exception("failed to republish to retry/DLQ")
        except aio_exc.AMQPError:
            logger.exception("RMQ connection lost, retrying ...")
            await asyncio.sleep(1)
            await _ensure()
