"""Background scheduler for token refresh, cleanup and task retries."""
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
    """Refresh OAuth tokens for all services if they are about to expire."""
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
            log.info("%s token refreshed owner=%s", service, owner_id or "-")
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("failed to refresh %s token owner=%s", service, owner_id or "-")

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
    """Clean deduplication table from old entries."""
    try:
        removed = await cleanup_older_than()
        if removed:
            log.info("dedup cleanup removed=%s", removed)
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception("dedup cleanup failed")


async def retry_overdue_tasks(limit: int = 100) -> None:
    """Republish tasks from DLQ back to retry queue."""
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
            log.info("requeued %s tasks from DLQ", count)
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception("retry_overdue_tasks failed")


async def _periodic(interval: int, coro):
    while True:
        try:
            await coro()
            log.info("%s completed successfully", coro.__name__)
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("%s failed", coro.__name__)
        await asyncio.sleep(interval)


async def run_forever() -> None:
    """Run scheduler tasks indefinitely."""
    await asyncio.gather(
        _periodic(300, refresh_service_tokens),
        _periodic(3600, cleanup_dedup_tables),
        _periodic(60, retry_overdue_tasks),
    )


if __name__ == "__main__":
    asyncio.run(run_forever())
