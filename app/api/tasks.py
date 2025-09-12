"""Обработчики фоновых задач, используемых потребителем RMQ."""

import time as _time

from app.adapters import avito as avito_adapt, hh as hh_adapt
from app.adapters.amo_client import AmoClient
from app.db.token_store import DbTokenStore
from app.http_client import get_http_client
from app.services.hh_autofill import autofill_hh_mapping
from app.services.worker.amo import (
    handle_amo_add_note,
    handle_amo_add_tags,
    handle_amo_update_status,
)
from app.services.worker.mirror import (
    handle_mirror_amo_to_tg,
    handle_mirror_bot_to_amo,
    handle_mirror_tg_to_amo,
)


async def handle_task(p: dict, _attempts: int = 0):  # pylint: disable=too-many-return-statements,too-many-branches
    """Обработать фоновую задачу в зависимости от платформы и действия."""
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
        nid = p.get("negotiation_id") or p.get("external_id")
        action_id = p.get("action_id") or p.get("target_state")
        if not nid or not action_id:
            raise RuntimeError(f"hh.set_state: missing nid/action_id in {p}")
        await hh_adapt.set_employer_state(
            response_id=nid,
            target_state=action_id,
            employer_id=p.get("owner_id"),
            client=get_http_client(),
        )
        return
    if p.get("platform") == "hh" and p.get("action") == "send_message":
        nid = p.get("negotiation_id") or p.get("external_id")
        if not nid:
            raise RuntimeError(f"hh.send_message: missing nid in {p}")
        await hh_adapt.send_message(
            response_id=nid,
            text=p.get("text") or "",
            employer_id=p.get("owner_id"),
            client=get_http_client(),
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

    if p.get("platform") == "amo" and p.get("action") == "amo_add_note":
        await handle_amo_add_note(p)
        return

    if p.get("platform") == "amo" and p.get("action") == "amo_add_tags":
        await handle_amo_add_tags(p)
        return

    if p.get("platform") == "amo" and p.get("action") == "amo_update_status":
        await handle_amo_update_status(p)
        return

    if p.get("platform") == "mirror" and p.get("action") == "amo_to_tg":
        await handle_mirror_amo_to_tg(p)
        return

    if p.get("platform") == "mirror" and p.get("action") == "tg_to_amo":
        await handle_mirror_tg_to_amo(p)
        return

    if p.get("platform") == "mirror" and p.get("action") == "bot_to_amo":
        await handle_mirror_bot_to_amo(p)
        return

    raise RuntimeError(f"Unknown task: {p}")


__all__ = ["handle_task"]
