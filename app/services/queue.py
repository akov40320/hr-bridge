"""Обёртка клиента RabbitMQ, предоставляющая удобные помощники для публикации и обработки задач.

Модуль предоставляет класс :class:`RabbitMQClient` и глобальный экземпляр ``rabbitmq``.
Класс хранит состояние соединения/канала и предоставляет методы публикации задач,
повторной публикации в очереди повтора/DLQ и потребления задач.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from typing import Awaitable, Callable

import aio_pika
import aio_pika.abc as amqp_abc
from aio_pika import exceptions as aio_exc

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _int(name: str, default: int) -> int:
    """Вернуть переменную окружения ``name`` как ``int``.

    Возвращает ``default``, если значение отсутствует или не является целым числом.
    """
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:  # pragma: no cover - defensive
        logger.warning("Некорректное целое число для %s, использую значение по умолчанию %s", name, default)
        return default


RMQ_PREFETCH = _int("RMQ_PREFETCH", 32)


class RabbitMQClient:
    """Поддерживает состояние соединения с RMQ и предоставляет вспомогательные методы."""

    def __init__(self) -> None:
        self._conn: amqp_abc.AbstractRobustConnection | None = None
        self._chan: amqp_abc.AbstractChannel | None = None
        self._exch: amqp_abc.AbstractExchange | None = None
        self._settings = None

    def _s(self):
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    async def _ensure(self) -> None:
        """Гарантировать наличие соединения, канала, обменника и очередей.

        Устанавливает соединение с RabbitMQ, объявляет основные, очередь повтора
        и очередь DLQ и привязывает их к обменнику.
        """
        if self._conn and not self._conn.is_closed and self._chan and not self._chan.is_closed:
            return

        s = self._s()
        self._conn = await aio_pika.connect_robust(
            s.RABBITMQ_URL.get_secret_value()
        )
        self._chan = await self._conn.channel(publisher_confirms=True)
        chan = self._chan
        assert chan is not None
        await chan.set_qos(prefetch_count=RMQ_PREFETCH)

        self._exch = await chan.declare_exchange(
            s.RMQ_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        exch = self._exch
        assert exch is not None

        await chan.declare_queue(s.RMQ_TASK_QUEUE, durable=True)
        await chan.declare_queue(
            s.RMQ_RETRY_QUEUE,
            durable=True,
            arguments={
                "x-message-ttl": s.RMQ_RETRY_TTL_MS,
                "x-dead-letter-exchange": s.RMQ_EXCHANGE,
                "x-dead-letter-routing-key": "tasks",
            },
        )
        await chan.declare_queue(s.RMQ_DLQ_QUEUE, durable=True)

        q_main = await chan.get_queue(s.RMQ_TASK_QUEUE)
        await q_main.bind(exch, routing_key="tasks")

        q_dlq = await chan.get_queue(s.RMQ_DLQ_QUEUE)
        await q_dlq.bind(exch, routing_key="tasks.dlq")

    async def connect(self) -> None:
        """Установить соединение с RabbitMQ, если оно ещё не установлено."""
        await self._ensure()

    async def close(self) -> None:
        """Закрыть соединение и канал, если они открыты."""
        try:
            if self._chan and not self._chan.is_closed:
                await self._chan.close()
        finally:
            if self._conn and not self._conn.is_closed:
                await self._conn.close()
        self._conn = self._chan = self._exch = None

    async def publish_task(self, payload: dict, attempts: int = 0) -> None:
        """Опубликовать задачу в основную очередь."""
        if not self._conn or self._conn.is_closed or not self._chan or self._chan.is_closed:
            await self._ensure()
        body = json.dumps({"payload": payload, "attempts": attempts}, ensure_ascii=False).encode()
        msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
        try:
            assert self._exch is not None
            await self._exch.publish(msg, routing_key="tasks")
        except aio_exc.AMQPError:
            await self._ensure()
            assert self._exch is not None
            await self._exch.publish(msg, routing_key="tasks")

    async def publish_retry(self, payload: dict, attempts: int) -> None:
        """Опубликовать задачу в очередь повтора."""
        if not self._conn or self._conn.is_closed or not self._chan or self._chan.is_closed:
            await self._ensure()

        s = self._s()
        body = json.dumps({"payload": payload, "attempts": attempts}, ensure_ascii=False).encode()
        msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
        try:
            assert self._chan is not None
            await self._chan.default_exchange.publish(
                msg, routing_key=s.RMQ_RETRY_QUEUE
            )
        except aio_exc.AMQPError:
            await self._ensure()
            assert self._chan is not None
            await self._chan.default_exchange.publish(
                msg, routing_key=s.RMQ_RETRY_QUEUE
            )

    async def publish_dlq(
        self, payload: dict, attempts: int, error: str | None = None
    ) -> None:
        """Опубликовать задачу в очередь DLQ."""
        if not self._conn or self._conn.is_closed or not self._chan or self._chan.is_closed:
            await self._ensure()
        obj = {"payload": payload, "attempts": attempts, "error": error}
        body = json.dumps(obj, ensure_ascii=False).encode()
        msg = aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
        try:
            assert self._exch is not None
            await self._exch.publish(msg, routing_key="tasks.dlq")
        except aio_exc.AMQPError:
            await self._ensure()
            assert self._exch is not None
            await self._exch.publish(msg, routing_key="tasks.dlq")

    async def requeue_dlq(self, count: int) -> int:
        """Переместить до ``count`` сообщений из DLQ обратно в основную очередь.

        Возвращает количество перемещённых сообщений.
        """
        if count <= 0:
            return 0
        if not self._conn or self._conn.is_closed or not self._chan or self._chan.is_closed:
            await self._ensure()
        s = self._s()
        assert self._chan is not None
        q_dlq = await self._chan.get_queue(s.RMQ_DLQ_QUEUE)
        moved = 0
        for _ in range(count):
            try:
                msg = await q_dlq.get(no_ack=False, fail=False)  # type: ignore[call-arg]
            except aio_exc.QueueEmpty:
                break
            if msg is None:
                break
            try:
                obj = json.loads(msg.body.decode())
                payload = obj.get("payload") or {}
            except Exception:  # pragma: no cover - defensive
                payload = {}
            if payload:
                await self.publish_task(payload, attempts=0)
                moved += 1
            await msg.ack()
        return moved

    async def consume(
        self, handler: Callable[..., Awaitable[None]], max_attempts: int = 10
    ) -> None:
        """Потреблять задачи и обрабатывать их через ``handler``.

        Сообщения подтверждаются только после успешной обработки. При ошибке
        сообщение перепубликуется в очередь повтора или DLQ в зависимости от
        количества попыток.
        """
        if not self._conn or self._conn.is_closed or not self._chan or self._chan.is_closed:
            await self._ensure()
        s = self._s()

        expects_attempts = len(inspect.signature(handler).parameters) > 1

        async def _worker() -> None:
            """Непрерывно получать сообщения из очереди и обрабатывать их."""
            q: amqp_abc.AbstractQueue | None = None
            while True:
                try:
                    if (
                        not self._conn
                        or self._conn.is_closed
                        or not self._chan
                        or self._chan.is_closed
                        or q is None
                    ):
                        await self._ensure()
                        assert self._chan is not None
                        q = await self._chan.get_queue(s.RMQ_TASK_QUEUE)

                    assert q is not None
                    async with q.iterator() as it:
                        async for message in it:
                            obj = None
                            attempts = 0
                            payload: dict[str, object] = {}
                            try:
                                obj = json.loads(message.body.decode("utf-8"))
                                payload = obj.get("payload") or {}
                                try:
                                    attempts = int(obj.get("attempts") or 0)
                                except (TypeError, ValueError):
                                    logger.warning(
                                        "Некорректное значение попыток: %s",
                                        obj.get("attempts"),
                                    )
                                    attempts = 0

                                if expects_attempts:
                                    await handler(payload, attempts)
                                else:
                                    await handler(payload)
                                await message.ack()
                            except (
                                json.JSONDecodeError,
                                aio_exc.AMQPError,
                                RuntimeError,
                            ) as e:  # pragma: no cover - mostly network
                                republished = False
                                cur_attempts = attempts + 1
                                try:
                                    if cur_attempts >= max_attempts:
                                        await self.publish_dlq(payload, cur_attempts, str(e))
                                        logger.exception(
                                            "отправлено в DLQ после попыток=%s", cur_attempts
                                        )
                                    else:
                                        await self.publish_retry(payload, cur_attempts)
                                        logger.exception(
                                            "отправлено в очередь повтора, попытка=%s", cur_attempts
                                        )
                                    republished = True
                                except aio_exc.AMQPError:  # pragma: no cover - log only
                                    logger.exception("не удалось перепубликовать в очередь повтора/DLQ")
                                finally:
                                    if republished:
                                        await message.ack()
                except asyncio.CancelledError:
                    break
                except aio_exc.AMQPError:  # pragma: no cover - network errors
                    logger.exception("соединение с RMQ потеряно, пытаюсь повторить ...")
                    q = None
                    await asyncio.sleep(1)
                    await self._ensure()

        workers = s.RMQ_CONSUMERS
        async with asyncio.TaskGroup() as tg:
            for _ in range(workers):
                tg.create_task(_worker())


rabbitmq = RabbitMQClient()


__all__ = ["RabbitMQClient", "rabbitmq"]
