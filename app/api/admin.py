"""Administrative and diagnostic endpoints."""

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
from app.api.oauth2 import OAuth2Config, ensure_fresh_access
from app.db.token_store import DbTokenStore

router = APIRouter()
admin = APIRouter()


logger = logging.getLogger(__name__)


def _s():
    return get_settings()


@router.get("/health")
async def health() -> dict[str, object]:
    """Return service health information."""

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
    """Return the current HeadHunter mapping."""

    return {"ok": True, "mapping": await hh_map_load()}


@admin.put("/hh-mapping")
async def put_hh_mapping(payload: dict) -> dict:
    """Replace the HeadHunter mapping with ``payload``."""

    return {"ok": True, "mapping": await hh_map_set(payload)}


@admin.post("/rmq-test")
async def rmq_test(
    payload: dict | None = None,
    queue_client: RabbitMQClient = Depends(lambda: rabbitmq),
):
    """Publish a test message to RabbitMQ."""

    msg = (payload or {}).get("msg", "hi")
    await queue_client.publish_task({"platform": "debug", "action": "echo", "msg": msg})
    return {"ok": True}


@admin.post("/dedup-clean")
async def dedup_clean(hours: int = 72) -> dict:
    """Clean deduplication entries older than ``hours``."""

    deleted = await cleanup_older_than(hours * 3600)
    logger.info("dedup cleanup removed=%s hours=%s", deleted, hours)
    return {"ok": True, "removed": deleted, "hours": hours}


@admin.get("/hh-states")
async def hh_states(
    owner_id: str | None = None,
    http_client: httpx.AsyncClient = Depends(get_http_client),
    s=Depends(get_settings),
):
    """Return the HeadHunter negotiation states."""

    try:
        access = await ensure_fresh_access(
            config=OAuth2Config(
                service="hh",
                token_url=s.HH_TOKEN_URL,
                client_id=s.HH_CLIENT_ID,
                client_secret=s.HH_CLIENT_SECRET,
                redirect_uri=s.HH_REDIRECT_URI,
                use_basic_auth=False,
                owner_id=owner_id,
            ),
            http_client=http_client,
        )
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
    """Queue a task that triggers HH autofill."""

    await queue_client.publish_task({"platform": "system", "action": "hh_autofill"})
    return {"ok": True, "queued": True}


__all__ = ["router", "admin"]
