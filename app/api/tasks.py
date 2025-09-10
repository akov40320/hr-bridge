"""Обработчики фоновых задач для потребителя RMQ."""

import time as _time

from app.adapters import avito as avito_adapt, hh as hh_adapt
from app.adapters.amo_client import AmoClient
from app.services.hh_autofill import autofill_hh_mapping
from app.db.token_store import DbTokenStore
from app.http_client import get_http_client


async def handle_task(p: dict, attempts: int = 0):
    """Обрабатывает фоновые задачи в зависимости от платформы и действия."""
    payload = p.get("payload") or {}
    if p.get("msg_key") is not None:
        payload.setdefault("msg_key", p["msg_key"])

    if p.get("platform") == "system" and p.get("action") == "hh_autofill":

        tok = await DbTokenStore("amo").load()
        if (
            not tok
            or not tok.get("access_token")
            or int(tok.get("expires_at", 0)) <= int(_time.time()) + 30
        ):
            raise RuntimeError("amo token missing/expired")

        await autofill_hh_mapping(get_http_client())
        return

    if p.get("platform") == "hh" and p.get("action") == "set_state":
        nid = payload.get("negotiation_id") or payload.get("external_id")
        action_id = payload.get("action_id") or payload.get("target_state")
        if not nid or not action_id:
            raise RuntimeError(f"hh.set_state: missing nid/action_id in {p}")
        await hh_adapt.set_employer_state(
            response_id=nid,
            target_state=action_id,
            employer_id=payload.get("owner_id"),
            client=get_http_client(),
        )
        return
    if p.get("platform") == "hh" and p.get("action") == "send_message":
        nid = payload.get("negotiation_id") or payload.get("external_id")
        if not nid:
            raise RuntimeError(f"hh.send_message: missing nid in {p}")
        await hh_adapt.send_message(
            response_id=nid,
            text=payload.get("text") or "",
            employer_id=payload.get("owner_id"),
            client=get_http_client(),
        )

    if p["platform"] == "avito" and p["action"] == "mark_read":
        await avito_adapt.mark_read(
            payload["external_id"],
            owner_id=payload.get("owner_id"),
            client=get_http_client(),
        )
        return

    if p["platform"] == "avito" and p["action"] == "send_message":
        await avito_adapt.send_message(
            payload["external_id"],
            payload.get("text") or "",
            owner_id=payload.get("owner_id"),
            client=get_http_client(),
        )
        return

    if p["platform"] == "amo" and p["action"] == "amo_create_lead":
        amo = await AmoClient.create(get_http_client())
        await amo.create_leads(payload["lead_body"])
        return

    raise RuntimeError(f"Unknown task: {p}")


__all__ = ["handle_task"]
