import logging
import re
import time, os
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse

from app.config import settings
from app.amo_client import AmoClient, ReauthRequired
from app.dedup import calc_key, check_and_store, cleanup_older_than
from app.queue import publish_task
from app.store import save_link, find_link
from app.hh_mapping import get as hh_map_get, load as hh_map_load, set_all as hh_map_set
from app.adapters import hh as hh_adapt, avito as avito_adapt
from app.token_store import TokenData, DbTokenStore
from app.guards import require_admin


logger = logging.getLogger(__name__)
router = APIRouter()
admin = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


# ---------- HH OAuth ----------
@router.get("/oauth/hh/start")
def hh_start():
    params = {
        "response_type": "code",
        "client_id": settings.HH_CLIENT_ID,
        "redirect_uri": settings.HH_REDIRECT_URI,
        "state": "hh1",  # можно оставить фикс, позже сделаем подпись
    }
    return RedirectResponse("https://hh.ru/oauth/authorize?" + urlencode(params))


@router.get("/oauth/hh/callback")
async def hh_callback(code: str | None = None, state: str | None = None):
    if not code:
        return {"ok": False, "error": "no code"}

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.HH_CLIENT_ID,
        "client_secret": settings.HH_CLIENT_SECRET,
        "redirect_uri": settings.HH_REDIRECT_URI,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as x:
            r = await x.post("https://api.hh.ru/token", data=data, headers={"Accept": "application/json"})
        if r.status_code >= 400:
            return {"ok": False, "provider": "hh", "step": "token", "status": r.status_code, "body": r.text}
        d = r.json()
    except Exception as e:
        return {"ok": False, "provider": "hh", "step": "token-exchange-exception", "error": str(e)}

    try:
        os.makedirs("secrets", exist_ok=True)
        expires_at = int(time.time()) + int(d.get("expires_in", 3600)) - 120
        await DbTokenStore("hh").save(TokenData(
            access_token=d["access_token"],
            refresh_token=d.get("refresh_token", ""),
            expires_at=expires_at
        ))
    except Exception as e:
        return {"ok": False, "provider": "hh", "step": "save-token", "error": str(e)}

    return {"ok": True}


# ---------- Avito OAuth ----------
@router.get("/oauth/avito/start")
def avito_start():
    if not (
            settings.AVITO_CLIENT_ID and settings.AVITO_REDIRECT_URI and settings.AVITO_AUTHORIZE_URL and settings.AVITO_TOKEN_URL):
        return {
            "ok": False,
            "error": "avito env not set",
            "need": {
                "AVITO_CLIENT_ID": bool(settings.AVITO_CLIENT_ID),
                "AVITO_REDIRECT_URI": bool(settings.AVITO_REDIRECT_URI),
                "AVITO_AUTHORIZE_URL": bool(settings.AVITO_AUTHORIZE_URL),
                "AVITO_TOKEN_URL": bool(settings.AVITO_TOKEN_URL),
            },
        }
    params = {
        "response_type": "code",
        "client_id": settings.AVITO_CLIENT_ID,
        "redirect_uri": settings.AVITO_REDIRECT_URI,
        "state": "av1",  # позже подпишем
    }
    if getattr(settings, "AVITO_SCOPE", ""):
        params["scope"] = settings.AVITO_SCOPE

    return RedirectResponse(f"{settings.AVITO_AUTHORIZE_URL}?{urlencode(params)}")


@router.get("/oauth/avito/callback")
async def avito_callback(code: str | None = None, state: str | None = None):
    if not code:
        return {"ok": False, "error": "no code"}

    if not (settings.AVITO_TOKEN_URL and settings.AVITO_CLIENT_ID and settings.AVITO_CLIENT_SECRET):
        return {"ok": False, "error": "avito token env not set"}

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.AVITO_REDIRECT_URI,
    }
    try:
        auth = httpx.BasicAuth(settings.AVITO_CLIENT_ID, settings.AVITO_CLIENT_SECRET)
        async with httpx.AsyncClient(timeout=30) as x:
            r = await x.post(settings.AVITO_TOKEN_URL, data=data, auth=auth)
        if r.status_code >= 400:
            return {"ok": False, "provider": "avito", "step": "token", "status": r.status_code, "body": r.text}
        tok = r.json()
    except Exception as e:
        return {"ok": False, "provider": "avito", "step": "token-exchange-exception", "error": str(e)}

    try:
        os.makedirs("secrets", exist_ok=True)
        expires_at = int(time.time()) + int(tok.get("expires_in", 86400)) - 120
        await DbTokenStore("avito").save(TokenData(
            access_token=tok.get("access_token", ""),
            refresh_token=tok.get("refresh_token", ""),
            expires_at=expires_at
        ))

    except Exception as e:
        return {"ok": False, "provider": "avito", "step": "save-token", "error": str(e)}

    return {"ok": True}


# ---------- вспомогалки ----------
def _events_from_form(form) -> list[tuple[int, int]]:
    keys = list(form.keys())
    idxs = set()
    for k in keys:
        m = re.match(r"leads\[status\]\[(\d+)\]\[id\]$", k)
        if m:
            idxs.add(int(m.group(1)))
    events = []
    for i in sorted(idxs):
        lead_id = int(form.get(f"leads[status][{i}][id]", 0) or 0)
        status_id = int(form.get(f"leads[status][{i}][status_id]", 0) or 0)
        if lead_id and status_id:
            events.append((lead_id, status_id))
    return events


@router.get("/health")
async def health():
    info = {"ok": True}
    try:
        amo = await DbTokenStore("amo").load()
        info["amo"] = {"status": "ok", "expires_in": max(0, amo["expires_at"] - int(time.time()))}
    except Exception as e:
        info["amo"] = {"status": "missing", "error": str(e)}
    return info


@router.get("/oauth/amo/callback")
async def oauth_callback(code: str | None = None, state: str | None = None):
    return {"ok": True, "code": code}


def route_type_by_text(text: str) -> str:
    t = (text or "").lower()
    if settings.ROUTING_KEYWORD_MASTER in t:
        return "master"
    if settings.ROUTING_KEYWORD_OPERATOR in t:
        return "operator"
    return "operator"


# ---------- входящие вебхуки от источников ----------
@router.post("/webhooks/hh")
async def webhook_hh(request: Request):
    raw = await request.body()
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    key = calc_key("hh", raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}
    payload["platform"] = "hh"
    return await _process_incoming(payload)


@router.post("/webhooks/avito")
async def webhook_avito(request: Request):
    raw = await request.body()
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    key = calc_key("avito", raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}
    payload["platform"] = "avito"
    return await _process_incoming(payload)


async def _process_incoming(payload: dict):
    title = payload.get("vacancy_title") or ""
    kind = route_type_by_text(title)
    amo = await AmoClient.create()

    if kind == "master":
        pipeline_id = settings.AMO_PIPELINE_ID_MASTER
        stage_id = settings.AMO_STAGE_ID_MASTER_NEW
    else:
        pipeline_id = settings.AMO_PIPELINE_ID_OPERATOR
        stage_id = settings.AMO_STAGE_ID_OPERATOR_NEW

    lead_name = f'{title} — {payload.get("applicant", {}).get("name", "кандидат")}'.strip(" —")

    # Логируем перед созданием лида
    logger.info(
        "lead:create platform=%s -> name=%s pipeline=%s stage=%s",
        payload.get("platform"), lead_name, pipeline_id, stage_id
    )

    body = [{"name": lead_name, "pipeline_id": pipeline_id, "status_id": stage_id}]
    try:
        created = await amo.create_leads(body)
    except ReauthRequired:
        await publish_task({
            "platform": payload.get("platform", "unknown"),
            "action": "amo_create_lead",
            "lead_body": body,
            "ts": int(time.time())
        })
        return {"ok": True, "queued": True, "reason": "reauth_required"}

    lead_id = created["_embedded"]["leads"][0]["id"]

    # Логируем после создания
    logger.info(
        "lead:created id=%s platform=%s vac=%s ext=%s",
        lead_id,
        payload.get("platform"),
        payload.get("vacancy_id"),
        payload.get("applicant", {}).get("id")
    )

    await save_link(
        lead_id=lead_id,
        platform=payload.get("platform", "unknown"),
        vacancy_id=str(payload.get("vacancy_id", "")),
        external_id=str(payload.get("applicant", {}).get("id") or "") or None
    )

    if kind == "master":
        bot_username = settings.TELEGRAM_MASTER_BOT_USERNAME
    else:
        bot_username = settings.TELEGRAM_OPERATOR_BOT_USERNAME

    deep_link = f"https://t.me/{bot_username}?start={lead_id}"
    text = f"Здравствуйте! Перейдите, пожалуйста, в Telegram-бот и пройдите короткий опрос: {deep_link}"

    if payload.get("platform") == "avito" and payload.get("applicant", {}).get("id"):
        # negotiation_id в external_id мы уже сохранили — публикуем задачу воркеру Avito
        await publish_task({
            "platform": "avito",
            "action": "send_message",
            "external_id": payload["applicant"]["id"],
            "text": text
        })

    await amo.add_tags(lead_id, [
        f'source:{payload.get("platform", "") or "unknown"}',
        f'type:{"мастер" if kind == "master" else "оператор"}'
    ])

    try:
        await amo.add_note(lead_id, f"Отправлена ссылка на TG-бота: {deep_link}")
    except Exception as e:
        logger.warning("add note (link sent) error: %s", e)

    return {"ok": True, "lead_id": lead_id}


# ---------- вебхук из Amo: складываем задачи на синхронизацию ----------
@router.post("/webhooks/amo")
async def amo_webhook(request: Request):
    raw = await request.body()
    key = calc_key("amo", raw)
    if not await check_and_store(key):
        return {"ok": True, "duplicate": True}

    hh_map_load()
    events: list[tuple[int, int]] = []

    # 1) Пытаемся JSON
    try:
        data = await request.json()
        if isinstance(data, dict) and data.get("leads", {}).get("status"):
            for it in data["leads"]["status"]:
                lead_id = int(it["id"])
                status_id = int(it.get("new_status_id") or it.get("status_id"))
                events.append((lead_id, status_id))
    except Exception:
        pass

    # 2) x-www-form-urlencoded
    if not events:
        form = await request.form()
        events = _events_from_form(form)

    # 3) Кладём в очередь на синхронизацию
    for lead_id, status_id in events:
        link = await find_link(lead_id)
        if not link:
            print("NO LINK FOR LEAD", lead_id)
            continue

        platform = link.get("platform")
        ext_id = link.get("external_id")

        if platform == "hh":
            state = hh_map_get(status_id)
            if state and ext_id:
                await publish_task({
                    "platform": "hh",
                    "action": "set_state",
                    "external_id": ext_id,
                    "target_state": state,
                    "lead_id": lead_id
                })
        elif platform == "avito":
            if settings.AVITO_MARK_READ_ON_STAGE_CHANGE and ext_id:
                await publish_task({
                    "platform": "avito",
                    "action": "mark_read",
                    "external_id": ext_id,
                    "lead_id": lead_id
                })

    return {"ok": True, "handled": len(events)}


# ------------- Админ-роуты -------------
@admin.get("/hh-mapping")
async def get_hh_mapping():
    return hh_map_load()


@admin.put("/admin/hh-mapping")
async def put_hh_mapping(payload: dict):
    return {"ok": True, "mapping": hh_map_set(payload)}


@admin.post("/admin/rmq-test")
async def rmq_test(payload: dict = None):
    msg = (payload or {}).get("msg", "hi")
    await publish_task({"platform": "debug", "action": "echo", "msg": msg})
    return {"ok": True}


async def _handle_task(p: dict):
    if p["platform"] == "hh" and p["action"] == "set_state":
        await hh_adapt.set_employer_state(p["external_id"], p["target_state"])
        return
    if p["platform"] == "avito" and p["action"] == "mark_read":
        await avito_adapt.mark_read(p["external_id"])
        return
    if p["platform"] == "amo" and p["action"] == "amo_create_lead":
        amo = await AmoClient.create()
        await amo.create_leads(p["lead_body"])
        return
    raise RuntimeError(f"Unknown task: {p}")


@admin.post("/dedup-clean")
async def dedup_clean(hours: int = 72):
    deleted = await cleanup_older_than(hours * 3600)
    logger.info("dedup cleanup removed=%s hours=%s", deleted, hours)
    return {"ok": True, "removed": deleted, "hours": hours}