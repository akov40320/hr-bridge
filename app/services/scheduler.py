"""Простой планировщик для периодических служебных задач.

Модуль предоставляет автономный процесс, который периодически обновляет
OAuth-токены, очищает таблицы дедупликации и повторяет задачи,
попавшие в очередь мёртвых писем. Предполагается, что он запускается как
отдельный сервис (см. ``docker-compose.yml``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Iterable

from app.api.oauth2 import OAuth2Config, refresh_tokens
from app.bootstrap import ensure_tokens
from app.core.config import get_settings
from app.core.logging_setup import setup_logging
from app.db import init_db
from app.db.token_store import DbTokenStore
from app.http_client import close_http_client, get_http_client
from app.services.dedup import cleanup_older_than
from app.services.queue import rabbitmq

logger = logging.getLogger(__name__)


async def _refresh_for_service(
    service: str, owner_ids: Iterable[str | None]
) -> None:
    """Обновить токены для владельцев *service* при приближении срока истечения."""

    s = get_settings()
    cfg_common = {
        "client_id": None,
        "client_secret": None,
        "token_url": "",
        "redirect_uri": None,
        "use_basic_auth": False,
    }
    if service == "amo":
        cfg_common.update(
            {
                "token_url": s.AMO_BASE_URL.rstrip("/") + "/oauth2/access_token",
                "client_id": s.AMO_CLIENT_ID,
                "client_secret": s.AMO_CLIENT_SECRET.get_secret_value(),
                "redirect_uri": s.AMO_REDIRECT_URI,
            }
        )
    elif service == "hh":
        cfg_common.update(
            {
                "token_url": s.HH_TOKEN_URL,
                "client_id": s.HH_CLIENT_ID,
                "client_secret": s.HH_CLIENT_SECRET.get_secret_value(),
                "redirect_uri": s.HH_REDIRECT_URI,
            }
        )
    elif service == "avito":
        cfg_common.update(
            {
                "token_url": s.AVITO_TOKEN_URL,
                "client_id": s.AVITO_CLIENT_ID,
                "client_secret": s.AVITO_CLIENT_SECRET.get_secret_value(),
                "redirect_uri": s.AVITO_REDIRECT_URI,
                "use_basic_auth": True,
            }
        )

    for owner_id in owner_ids:
        store = DbTokenStore(service, owner_id)
        try:
            if not await store.will_expire_soon():
                continue
            data = await store.load()
        except Exception:  # pragma: no cover - defensive
            logger.exception("не удалось загрузить токен для %s/%s", service, owner_id)
            continue

        config = OAuth2Config(service=service, owner_id=owner_id, **cfg_common)
        try:
            await refresh_tokens(config=config, refresh_token=data["refresh_token"], http_client=get_http_client())
            logger.info("обновлён токен %s для %s", service, owner_id or "default")
        except Exception:  # pragma: no cover - defensive
            logger.exception("не удалось обновить токен для %s/%s", service, owner_id)


TOKEN_REFRESH_INTERVAL = 300  # seconds
DEDUP_INTERVAL = 3600
RETRY_INTERVAL = 60


async def refresh_tokens_loop() -> None:
    """Периодически обновлять OAuth-токены для всех сервисов."""

    while True:
        try:
            amo_owners = [None]
            hh_owners = await DbTokenStore.list_owners("hh")
            avito_owners = await DbTokenStore.list_owners("avito")
            await _refresh_for_service("amo", amo_owners)
            await _refresh_for_service("hh", hh_owners)
            await _refresh_for_service("avito", avito_owners)
        except Exception:  # pragma: no cover - defensive
            logger.exception("сбой цикла обновления токенов")
        await asyncio.sleep(TOKEN_REFRESH_INTERVAL)


async def dedup_cleanup_loop() -> None:
    """Периодически удалять устаревшие записи дедупликации."""

    while True:
        try:
            removed = await cleanup_older_than()
            if removed:
                logger.info("очистка дедупликации удалено=%s", removed)
        except Exception:  # pragma: no cover - defensive
            logger.exception("сбой очистки дедупликации")
        await asyncio.sleep(DEDUP_INTERVAL)


async def _republish_from_queue(queue_name: str) -> int:
    """Перепубликовать все сообщения из ``queue_name`` обратно в очередь задач."""

    await rabbitmq.connect()
    chan = rabbitmq._chan  # type: ignore[attr-defined]
    if chan is None:
        return 0
    queue = await chan.get_queue(queue_name)
    count = 0
    while True:
        msg = await queue.get(fail=False)
        if msg is None:
            break
        try:
            obj = json.loads(msg.body.decode())
            payload = obj.get("payload") or {}
            attempts = int(obj.get("attempts") or 0)
            await rabbitmq.publish_task(payload, attempts)
            await msg.ack()
            count += 1
        except Exception:  # pragma: no cover - defensive
            await msg.reject(requeue=False)
    return count


async def retry_tasks_loop() -> None:
    """Периодически повторять задачи из очереди мёртвых писем."""

    s = get_settings()
    queue_name = s.RMQ_DLQ_QUEUE
    while True:
        try:
            cnt = await _republish_from_queue(queue_name)
            if cnt:
                logger.info("перепубликовано %s задач из DLQ", cnt)
        except Exception:  # pragma: no cover - defensive
            logger.exception("сбой цикла повторов")
        await asyncio.sleep(RETRY_INTERVAL)


async def main() -> None:
    """Точка входа, запускающая все циклы планировщика."""

    setup_logging("INFO")
    await init_db()
    await ensure_tokens()
    await rabbitmq.connect()
    try:
        await asyncio.gather(
            refresh_tokens_loop(),
            dedup_cleanup_loop(),
            retry_tasks_loop(),
        )
    finally:
        await rabbitmq.close()
        await close_http_client()


if __name__ == "__main__":
    asyncio.run(main())
