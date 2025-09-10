"""Administrative and diagnostic endpoints."""

import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from pydantic import RootModel

from app.http_client import get_http_client
from app.core.config import get_settings
from app.services.dedup import cleanup_older_than
from app.services.hh_mapping import load as hh_map_load, set_all as hh_map_set
from app.services.queue import rabbitmq, RabbitMQClient
from app.api.oauth2 import OAuth2Config, ensure_fresh_access
from app.db.token_store import DbTokenStore
from app.api.hh_webhook import ensure_hh_webhook
from app.api.avito_webhooks import ensure_avito_webhooks
from app.db.db import get_session
from app.db.models import Token
from sqlalchemy import select
from app.bootstrap import ensure_tokens
from app.api._webhook_common import process_job_board_webhook
from app.services.payload_parsers import (
    parse_hh_payload,
    extract_avito_payload,
    parse_avito_payload,
)
from app.services.lead_processor import send_invite
from app.models import IncomingPayload, Applicant
from app.store import find_link
from app.adapters.amo_client import AmoClient
from app.services.hh_status_sync import sync_hh_status

router = APIRouter()
admin = APIRouter()


class HHMapping(RootModel[dict[str, str]]):
    """HeadHunter status mapping payload."""

    pass


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

    return {"ok": True, "mapping": hh_map_load()}


@admin.put("/hh-mapping")
async def put_hh_mapping(payload: HHMapping) -> dict:
    """Replace the HeadHunter mapping with ``payload``."""

    try:
        new_mapping = hh_map_set(payload.model_dump())
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("invalid hh mapping payload: %s", exc)
        raise HTTPException(status_code=400, detail=f"invalid mapping: {exc}")
    return {"ok": True, "mapping": new_mapping}


@admin.post("/rmq-test")
async def rmq_test(
    payload: dict | None = None,
    queue_client: RabbitMQClient = Depends(lambda: rabbitmq),
):
    """Publish a test message to RabbitMQ."""

    msg = (payload or {}).get("msg", "hi")
    await queue_client.publish_task({"platform": "debug", "action": "echo", "payload": {"msg": msg}})
    return {"ok": True}


@admin.post("/dedup-clean")
async def dedup_clean(hours: int = 72) -> dict:
    """Clean deduplication entries older than ``hours``."""

    deleted = await cleanup_older_than(hours * 3600)
    logger.info("dedup cleanup removed=%s hours=%s", deleted, hours)
    return {"ok": True, "removed": deleted, "hours": hours}


@admin.post("/dlq/requeue")
async def dlq_requeue(
    n: int = 10, queue_client: RabbitMQClient = Depends(lambda: rabbitmq)
) -> dict:
    """Requeue up to ``n`` messages from the dead-letter queue."""

    moved = await queue_client.requeue_dlq(n)
    return {"ok": True, "requeued": moved}


@admin.post("/replay/lead")
async def replay_lead(
    platform: str,
    request: Request,
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> dict:
    """Replay a missed job board webhook without deduplication."""

    if platform not in {"hh", "avito"}:
        raise HTTPException(status_code=400, detail="unknown platform")
    parsers = {
        "hh": parse_hh_payload,
        "avito": lambda b: parse_avito_payload(extract_avito_payload(b)),
    }
    raw = await request.body()
    parser = parsers[platform]
    return await process_job_board_webhook(
        platform, raw, http_client, parser, skip_dedup=True
    )


@admin.post("/replay/survey-invite")
async def replay_survey_invite(
    lead_id: int,
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> dict:
    """Resend Telegram survey invite for the given lead."""

    link = await find_link(lead_id)
    if not link or not link.get("external_id"):
        raise HTTPException(status_code=404, detail="lead link not found")
    amo = await AmoClient.create(http_client)
    lead = await amo.get_lead(lead_id)
    s = get_settings()
    pipeline_id = lead.get("pipeline_id")
    kind = (
        "master" if pipeline_id == s.AMO_PIPELINE_ID_MASTER else "operator"
    )
    payload = IncomingPayload(
        platform=link["platform"],
        owner_id=link.get("owner_id"),
        vacancy_id=link.get("vacancy_id"),
        applicant=Applicant(id=str(link["external_id"]), name="replay"),
        kind=kind,
    )
    await send_invite(payload, lead_id)
    return {"ok": True}


@admin.post("/status-sync/lead")
async def status_sync_lead(
    lead_id: int,
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> dict:
    """Synchronize the current lead status with HeadHunter."""

    link = await find_link(lead_id)
    if not link:
        raise HTTPException(status_code=404, detail="lead link not found")
    amo = await AmoClient.create(http_client)
    lead = await amo.get_lead(lead_id)
    status_id = lead.get("status_id")
    if not isinstance(status_id, int):
        raise HTTPException(status_code=400, detail="invalid status")
    await sync_hh_status(lead_id, status_id, link, http_client)
    return {"ok": True, "status_id": status_id}


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
                client_secret=s.HH_CLIENT_SECRET.get_secret_value(),
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

    await queue_client.publish_task({"platform": "system", "action": "hh_autofill", "payload": {}})
    return {"ok": True, "queued": True}


@admin.post("/hh-webhook/ensure")
async def hh_webhook_ensure(http_client: httpx.AsyncClient = Depends(get_http_client)) -> dict:
    """Trigger idempotent HH webhook registration."""

    await ensure_hh_webhook(http_client)
    return {"ok": True}


@admin.post("/avito-webhook/ensure")
async def avito_webhook_ensure(http_client: httpx.AsyncClient = Depends(get_http_client)) -> dict:
    """Trigger idempotent Avito webhook registration."""

    await ensure_avito_webhooks(http_client)
    return {"ok": True}


@admin.get("/tokens/owners")
async def tokens_owners() -> dict:
    """Return all token owners with service and expiration."""

    async with get_session() as s:
        rows = (await s.execute(select(Token.service, Token.owner_id, Token.expires_at))).all()
    items = [
        {"service": r[0], "owner_id": r[1], "expires_at": r[2]} for r in rows
    ]
    return {"ok": True, "items": items}


@admin.post("/tokens/refresh")
async def tokens_refresh(
    platform: str,
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> dict:
    """Refresh access tokens for all owners of *platform*."""

    if platform not in {"hh", "avito", "amo"}:
        raise HTTPException(status_code=400, detail="unknown platform")

    s = get_settings()
    cfg: dict[str, object] = {
        "token_url": "",
        "client_id": "",
        "client_secret": "",
        "redirect_uri": None,
        "use_basic_auth": False,
    }
    if platform == "hh":
        cfg.update(
            {
                "token_url": s.HH_TOKEN_URL,
                "client_id": s.HH_CLIENT_ID,
                "client_secret": s.HH_CLIENT_SECRET.get_secret_value(),
                "redirect_uri": s.HH_REDIRECT_URI,
            }
        )
    elif platform == "avito":
        cfg.update(
            {
                "token_url": s.AVITO_TOKEN_URL,
                "client_id": s.AVITO_CLIENT_ID,
                "client_secret": s.AVITO_CLIENT_SECRET.get_secret_value(),
                "redirect_uri": s.AVITO_REDIRECT_URI,
                "use_basic_auth": True,
            }
        )
    else:  # amo
        cfg.update(
            {
                "token_url": s.AMO_BASE_URL.rstrip("/") + "/oauth2/access_token",
                "client_id": s.AMO_CLIENT_ID,
                "client_secret": s.AMO_CLIENT_SECRET.get_secret_value(),
                "redirect_uri": s.AMO_REDIRECT_URI,
            }
        )

    owners = [None] if platform == "amo" else await DbTokenStore.list_owners(platform)
    refreshed: list[str | None] = []
    errors: dict[str, str] = {}
    for owner_id in owners:
        try:
            await ensure_fresh_access(
                config=OAuth2Config(service=platform, owner_id=owner_id, **cfg),
                margin_sec=10**9,
                http_client=http_client,
            )
            refreshed.append(owner_id)
        except Exception as exc:  # pragma: no cover - defensive
            errors[str(owner_id)] = str(exc)
    return {"ok": True, "refreshed": refreshed, "errors": errors}


@admin.post("/tokens/ensure")
async def tokens_ensure() -> dict:
    """Reload tokens from environment variables."""

    await ensure_tokens()
    return {"ok": True}


__all__ = ["router", "admin"]
