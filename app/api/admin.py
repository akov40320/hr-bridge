"""Administrative and diagnostic endpoints."""

import logging
import time

import httpx
from fastapi import APIRouter, Depends
from app.http_client import get_http_client

from app.core.config import settings
from app.services.dedup import cleanup_older_than
from app.services.hh_mapping import load as hh_map_load, set_all as hh_map_set
from app.services.queue import publish_task
from app.db.token_store import DbTokenStore

router = APIRouter()
admin = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/health")
async def health():
    info: dict[str, object] = {"ok": True}
    try:
        amo = await DbTokenStore("amo").load()
        info["amo"] = {
            "status": "ok",
            "expires_in": max(0, amo["expires_at"] - int(time.time())),
        }
    except Exception as e:
        info["amo"] = {"status": "missing", "error": str(e)}
    return info


@admin.get("/hh-mapping")
async def get_hh_mapping():
    return {"ok": True, "mapping": hh_map_load()}


@admin.put("/hh-mapping")
async def put_hh_mapping(payload: dict):
    return {"ok": True, "mapping": hh_map_set(payload)}


@admin.post("/rmq-test")
async def rmq_test(payload: dict | None = None):
    msg = (payload or {}).get("msg", "hi")
    await publish_task({"platform": "debug", "action": "echo", "msg": msg})
    return {"ok": True}


@admin.post("/dedup-clean")
async def dedup_clean(hours: int = 72):
    deleted = await cleanup_older_than(hours * 3600)
    logger.info("dedup cleanup removed=%s hours=%s", deleted, hours)
    return {"ok": True, "removed": deleted, "hours": hours}


@admin.get("/hh-states")
async def hh_states(
    owner_id: str | None = None,
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    try:
        tok = await DbTokenStore("hh", owner_id).load()
    except Exception as e:
        return {"ok": False, "error": f"no hh token: {e}"}

    r = await http_client.get(
        f"{settings.HH_API_BASE.rstrip('/')}/dictionaries",
        headers={
            "Authorization": f"Bearer {tok['access_token']}",
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
async def hh_autofill_admin():
    await publish_task({"platform": "system", "action": "hh_autofill"})
    return {"ok": True, "queued": True}


__all__ = ["router", "admin"]

