import re
from fastapi import APIRouter, Request
from app.config import settings
from app.amo_client import AmoClient
from app.store import save_link, enqueue_pending, find_link, replay_pending
from app.hh_mapping import get as hh_map_get, load as hh_map_load, set_all as hh_map_set
from app.adapters import hh as hh_adapt, avito as avito_adapt
from urllib.parse import urlencode
from fastapi.responses import RedirectResponse

router = APIRouter()

# --- HH OAuth ---
@router.get("/oauth/hh/start")
def hh_start():
    params = {
        "response_type": "code",
        "client_id": settings.HH_CLIENT_ID,
        "redirect_uri": settings.HH_REDIRECT_URI,
        "state": "hh1",
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
    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post("https://api.hh.ru/token", data=data)
    r.raise_for_status()
    d = r.json()
    expires_at = int(time.time()) + int(d.get("expires_in", 3600)) - 120
    FileTokenStore("secrets/hh_token.json").save(TokenData(
        access_token=d["access_token"],
        refresh_token=d.get("refresh_token", ""),
        expires_at=expires_at
    ))
    return {"ok": True}


@router.get("/oauth/avito/start")
def avito_start():
    if not settings.AVITO_AUTHORIZE_URL:
        return {"ok": False, "error": "AVITO_AUTHORIZE_URL not set"}
    params = {
        "response_type": "code",
        "client_id": settings.AVITO_CLIENT_ID,
        "redirect_uri": settings.AVITO_REDIRECT_URI,
        "state": "av1",
    }
    return RedirectResponse(settings.AVITO_AUTHORIZE_URL + "?" + urlencode(params))


@router.get("/oauth/avito/callback")
async def avito_callback(code: str | None = None, state: str | None = None):
    if not code:
        return {"ok": False, "error": "no code"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.AVITO_CLIENT_ID,
        "client_secret": settings.AVITO_CLIENT_SECRET,
        "redirect_uri": settings.AVITO_REDIRECT_URI,
    }
    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.post("https://api.avito.ru/token", data=data)
    r.raise_for_status()
    d = r.json()
    expires_at = int(time.time()) + int(d.get("expires_in", 3600)) - 120
    FileTokenStore("secrets/avito_token.json").save(TokenData(
        access_token=d["access_token"],
        refresh_token=d.get("refresh_token", ""),
        expires_at=expires_at
    ))
    return {"ok": True}

def _events_from_form(form) -> list[tuple[int, int]]:
    """Парсит ключи вида leads[status][0][id] / [status_id] из form-данных."""
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
    return {"ok": True}


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


@router.post("/webhooks/hh")
async def webhook_hh(payload: dict):
    payload["platform"] = "hh"
    return await _process_incoming(payload)


@router.post("/webhooks/avito")
async def webhook_avito(payload: dict):
    payload["platform"] = "avito"
    return await _process_incoming(payload)


async def _process_incoming(payload: dict):
    title = payload.get("vacancy_title") or ""
    kind = route_type_by_text(title)
    amo = AmoClient()

    if kind == "master":
        pipeline_id = settings.AMO_PIPELINE_ID_MASTER
        stage_id = settings.AMO_STAGE_ID_MASTER_NEW
    else:
        pipeline_id = settings.AMO_PIPELINE_ID_OPERATOR
        stage_id = settings.AMO_STAGE_ID_OPERATOR_NEW

    lead_name = f'{title} — {payload.get("applicant", {}).get("name", "кандидат")}'.strip(" —")
    body = [{"name": lead_name, "pipeline_id": pipeline_id, "status_id": stage_id}]
    created = await amo.create_leads(body)
    lead_id = created["_embedded"]["leads"][0]["id"]

    # сохраним связь (external_id пока можем не знать — пусть будет None)
    save_link(
        lead_id=lead_id,
        platform=payload.get("platform", "unknown"),
        vacancy_id=str(payload.get("vacancy_id", "")),
        external_id=str(payload.get("applicant", {}).get("id") or "") or None
    )

    # теги отдельным PATCH (как раньше)
    await amo.add_tags(lead_id, [
        settings.AMO_TAG_WENT_TO_BOT,
        f'source:{payload.get("platform", "") or "unknown"}',
        f'type:{"мастер" if kind == "master" else "оператор"}'
    ])

    return {"ok": True, "lead_id": lead_id}


# ------------- Вебхук Amo: складываем задачи синхры -------------
@router.post("/webhooks/amo")
async def amo_webhook(request: Request):
    hh_map_load()  # карта Amo→hh в память
    events: list[tuple[int, int]] = []

    # 1) Пытаемся как JSON (будущие форматы)
    try:
        data = await request.json()
        if isinstance(data, dict) and data.get("leads", {}).get("status"):
            for it in data["leads"]["status"]:
                lead_id = int(it["id"])
                status_id = int(it.get("new_status_id") or it.get("status_id"))
                events.append((lead_id, status_id))
    except Exception:
        pass  # это нормально для x-www-form-urlencoded

    # 2) Если JSON не подошёл — читаем form (нужен python-multipart)
    if not events:
        form = await request.form()  # ← работает благодаря python-multipart
        events = _events_from_form(form)

    # 3) Складываем задачи синхронизации
    for lead_id, status_id in events:
        link = find_link(lead_id)
        if not link:
            print("NO LINK FOR LEAD", lead_id)
            continue

        platform = link.get("platform")
        ext_id = link.get("external_id")

        if platform == "hh":
            state = hh_map_get(status_id)
            if state and ext_id:
                enqueue_pending({
                    "platform": "hh",
                    "action": "set_state",
                    "external_id": ext_id,
                    "target_state": state,
                    "lead_id": lead_id
                })
        elif platform == "avito":
            if settings.AVITO_MARK_READ_ON_STAGE_CHANGE and ext_id:
                enqueue_pending({
                    "platform": "avito",
                    "action": "mark_read",
                    "external_id": ext_id,
                    "lead_id": lead_id
                })

    return {"ok": True, "handled": len(events)}


# ------------- Админ-роуты -------------
@router.get("/admin/hh-mapping")
async def get_hh_mapping():
    return hh_map_load()


@router.put("/admin/hh-mapping")
async def put_hh_mapping(payload: dict):
    # payload: { "78909402":"phone_interview", ... }
    return {"ok": True, "mapping": hh_map_set(payload)}


@router.post("/admin/sync/replay")
async def admin_replay():
    def _hh_handler(task: dict):
        hh_adapt.set_employer_state(task["external_id"], task["target_state"])

    def _avito_handler(task: dict):
        avito_adapt.mark_read(task["external_id"])

    res = replay_pending(
        hh_enabled=settings.HH_SYNC_ENABLED,
        avito_enabled=settings.AVITO_SYNC_ENABLED,
        handler_hh=_hh_handler,
        handler_avito=_avito_handler
    )
    return {"ok": True, **res}
