"""Фоновый планировщик для обновления токенов, очистки и повторных попыток задач."""
# pylint: disable=line-too-long

import asyncio
import json
import logging

from app.core.logging_setup import setup_logging
from app.core.config import get_settings
from app.api.oauth2 import OAuth2Config, refresh_tokens
from app.core.oauth_helpers import hh_config, avito_config
from app.db.token_store import DbTokenStore
from app.services.dedup import cleanup_older_than
from app.services.queue import rabbitmq
from app.http_client import get_http_client


setup_logging("INFO")
log = logging.getLogger(__name__)


async def refresh_service_tokens() -> None:
    """Обновить OAuth‑токены всех сервисов, если срок их действия скоро истечёт."""
    s = get_settings()
    client = get_http_client()

    async def _refresh(service: str, *, owner_id: str | None = None, cfg: OAuth2Config | None = None):
        store = DbTokenStore(service, owner_id)
        if not await store.will_expire_soon():
            return
        try:
            data = await store.load()
        except RuntimeError:
            return
        conf = cfg
        if conf is None:
            token_url = (
                f"{s.AMO_BASE_URL.rstrip('/')}/oauth2/access_token"
                if service == "amo"
                else getattr(s, f"{service.upper()}_TOKEN_URL")
            )
            conf = OAuth2Config(
                service=service,
                token_url=token_url,
                client_id=getattr(s, f"{service.upper()}_CLIENT_ID"),
                client_secret=getattr(s, f"{service.upper()}_CLIENT_SECRET"),
                redirect_uri=getattr(s, f"{service.upper()}_REDIRECT_URI", ""),
                owner_id=owner_id,
            )
        try:
            await refresh_tokens(
                config=conf, refresh_token=data["refresh_token"], http_client=client
            )
            log.info("токен %s обновлён owner=%s", service, owner_id or "-")
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("не удалось обновить токен %s owner=%s", service, owner_id or "-")

    await _refresh("amo")

    hh_owners = await DbTokenStore.list_owners("hh")
    for owner in hh_owners:
        cfg = hh_config(owner)
        await _refresh("hh", owner_id=owner, cfg=cfg)

    avito_owners = await DbTokenStore.list_owners("avito")
    for owner in avito_owners:
        cfg = avito_config(owner)
        await _refresh("avito", owner_id=owner, cfg=cfg)


async def cleanup_dedup_tables() -> None:
    """Очистить таблицу дедупликации от старых записей."""
    try:
        removed = await cleanup_older_than()
        if removed:
            log.info("очистка dedup удалено=%s", removed)
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception("ошибка очистки dedup")


async def retry_overdue_tasks(limit: int = 100) -> None:
    """Переопубликовать задачи из DLQ обратно в очередь повторов."""
    try:
        await rabbitmq.connect()
        s = get_settings()
        assert rabbitmq._chan is not None  # type: ignore[attr-defined]  # pylint: disable=protected-access
        q = await rabbitmq._chan.get_queue(s.RMQ_DLQ_QUEUE)  # type: ignore[attr-defined]  # pylint: disable=protected-access
        count = 0
        for _ in range(limit):
            msg = await q.get(fail=False)
            if msg is None:
                break
            try:
                obj = json.loads(msg.body.decode("utf-8"))
                payload = obj.get("payload") or {}
                attempts = int(obj.get("attempts") or 0)
                await rabbitmq.publish_retry(payload, attempts)
                count += 1
            finally:
                await msg.ack()
        if count:
            log.info("перепоставлено %s задач из DLQ", count)
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception("ошибка retry_overdue_tasks")


async def _periodic(interval: int, coro):
    while True:
        try:
            await coro()
            log.info("%s успешно завершён", coro.__name__)
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("%s завершился ошибкой", coro.__name__)
        await asyncio.sleep(interval)


async def run_forever() -> None:
    """Запускать задания планировщика бесконечно."""
    await asyncio.gather(
        _periodic(300, refresh_service_tokens),
        _periodic(3600, cleanup_dedup_tables),
        _periodic(60, retry_overdue_tasks),
    )


if __name__ == "__main__":
    asyncio.run(run_forever())
