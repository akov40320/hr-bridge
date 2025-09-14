"""Административные и диагностические эндпоинты."""

import logging
import time

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError

from app.http_client import get_http_client
from app.core.config import get_settings
from app.services.dedup import cleanup_older_than
from app.services.hh_mapping import load as hh_map_load, set_all as hh_map_set
from app.services.queue import rabbitmq, RabbitMQClient
from app.core.oauth_helpers import hh_access
from app.db.token_store import DbTokenStore
from app.adapters import avito as avito_adapter

router = APIRouter()
admin = APIRouter()


logger = logging.getLogger(__name__)


def _s():
    return get_settings()


@router.get("/health")
async def health() -> dict[str, object]:
    """Вернуть информацию о состоянии сервиса (health)."""

    info: dict[str, object] = {"ok": True}
    try:
        amo = await DbTokenStore("amo").load()
        info["amo"] = {
            "status": "ok",
            "expires_in": max(0, amo["expires_at"] - int(time.time())),
        }
    except (RuntimeError, SQLAlchemyError) as exc:
        info["amo"] = {"status": "missing", "error": str(exc)}
    return info


@admin.get("/hh-mapping")
async def get_hh_mapping() -> dict:
    """Вернуть текущую таблицу сопоставления (mapping) HeadHunter."""

    return {"ok": True, "mapping": await hh_map_load()}


@admin.put("/hh-mapping")
async def put_hh_mapping(payload: dict) -> dict:
    """Заменить таблицу сопоставления HeadHunter на ``payload``."""

    return {"ok": True, "mapping": await hh_map_set(payload)}


@admin.post("/rmq-test")
async def rmq_test(
    payload: dict | None = None,
    queue_client: RabbitMQClient = Depends(lambda: rabbitmq),
):
    """Опубликовать тестовое сообщение в RabbitMQ."""

    msg = (payload or {}).get("msg", "hi")
    await queue_client.publish_task({"platform": "debug", "action": "echo", "msg": msg})
    return {"ok": True}


@admin.post("/dedup-clean")
async def dedup_clean(hours: int = 72) -> dict:
    """Очистить записи дедупликации старше ``hours`` часов."""

    deleted = await cleanup_older_than(hours * 3600)
    logger.info("дедуп‑очистка удалено=%s часов=%s", deleted, hours)
    return {"ok": True, "removed": deleted, "hours": hours}


@admin.get("/hh-states")
async def hh_states(
    owner_id: str | None = None,
    http_client: httpx.AsyncClient = Depends(get_http_client),
    s=Depends(get_settings),
):
    """Вернуть список состояний переговоров HeadHunter."""

    try:
        access = await hh_access(http_client, owner_id)
    except (RuntimeError, SQLAlchemyError) as exc:
        return {"ok": False, "error": f"no hh token: {exc}"}

    r = await http_client.get(
        f"{s.HH_API_BASE.rstrip('/')}/dictionaries",
        headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/json",
        },
        timeout=15,
    )
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "body": r.text}

    items = (r.json() or {}).get("negotiations_state") or []
    return {
        "ok": True,
        "states": [{"id": it.get("id"), "name": it.get("name")} for it in items if it],
    }


@admin.post("/hh-autofill")
async def hh_autofill_admin(
    queue_client: RabbitMQClient = Depends(lambda: rabbitmq),
):
    """Поставить в очередь задачу автозаполнения HH."""

    await queue_client.publish_task({"platform": "system", "action": "hh_autofill"})
    return {"ok": True, "queued": True}


@admin.get("/avito-items")
async def avito_items(
    owner_id: str,  # Avito account_id
    limit: int = 50,
    offset: int = 0,
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    """List Avito ads (items) for a given `owner_id` (account_id).

    Requires Avito OAuth token stored for that `owner_id`.
    Returns raw Avito JSON and a best-effort `items` extraction for convenience.
    """
    try:
        # Ensure there is a token; will raise if missing
        await DbTokenStore("avito", owner_id).load()
    except (RuntimeError, SQLAlchemyError) as exc:
        return {"ok": False, "error": f"no avito token for owner_id={owner_id}: {exc}"}

    try:
        js = await avito_adapter.list_items(
            owner_id=owner_id,
            client=http_client,
            limit=limit,
            offset=offset,
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        return {"ok": False, "error": str(e)}

    # Try common shapes: {items: [...]}, {result: {items: [...]}}
    items = []
    if isinstance(js, dict):
        if isinstance(js.get("items"), list):
            items = js.get("items") or []
        elif isinstance(js.get("result"), dict) and isinstance(js["result"].get("items"), list):
            items = js["result"]["items"] or []

    return {
        "ok": True,
        "owner_id": owner_id,
        "limit": limit,
        "offset": offset,
        "items": items,
        "raw": js,
    }


__all__ = ["router", "admin"]
