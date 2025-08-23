"""Background task handlers used by RMQ consumer."""

import time as _time

from app.adapters import avito as avito_adapt, hh as hh_adapt
from app.adapters.amo_client import AmoClient
from app.services.hh_autofill import autofill_hh_mapping
from app.db.token_store import DbTokenStore
from app.http_client import get_http_client


async def handle_task(p: dict):
    """Process background tasks based on platform and action."""
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

    if p["platform"] == "hh" and p["action"] == "set_state":
        client = get_http_client()
        await hh_adapt.set_employer_state(
            response_id=p["external_id"],
            target_state=p["target_state"],
            employer_id=p.get("owner_id"),
            client=client,
        )
        return

    if p["platform"] == "avito" and p["action"] == "mark_read":
        await avito_adapt.mark_read(
            p["external_id"],
            owner_id=p.get("owner_id"),
            client=get_http_client(),
        )
        return

    if p["platform"] == "avito" and p["action"] == "send_message":
        await avito_adapt.send_message(
            p["external_id"],
            p.get("text") or "",
            owner_id=p.get("owner_id"),
            client=get_http_client(),
        )
        return

    if p["platform"] == "amo" and p["action"] == "amo_create_lead":
        amo = await AmoClient.create(get_http_client())
        await amo.create_leads(p["lead_body"])
        return

    raise RuntimeError(f"Unknown task: {p}")


__all__ = ["handle_task"]
