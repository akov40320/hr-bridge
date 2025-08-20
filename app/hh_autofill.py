# app/hh_autofill.py
import re
import logging
import httpx

from app.config import settings
from app.token_store import DbTokenStore
from app.hh_mapping import load as hh_map_load, set_all as hh_map_set

log = logging.getLogger(__name__)


def _norm_stage_name(s: str) -> str:
    s = (s or "").strip().lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", s)


# Название стадии Amo (нормализованное) -> код HH
_STAGE_NAME_TO_HH = {
    "отклик": "response",
    "первичныйконтакт": "phone_interview",
    "собеседование": "interview",
    "выходнаработу": "hired",
    "отказ": "discard_by_employer",
    "закрытоинереализовано": "discard_by_employer",
}


async def _fetch_pipeline_statuses(pipeline_id: int) -> list[dict]:
    try:
        tok = await DbTokenStore("amo").load()
    except Exception as e:
        log.warning("hh-autofill: no amo token: %s", e)
        return []

    url = settings.AMO_BASE_URL.rstrip("/") + f"/api/v4/leads/pipelines/{pipeline_id}"
    try:
        async with httpx.AsyncClient(timeout=20) as x:
            r = await x.get(url, headers={
                "Authorization": f"Bearer {tok['access_token']}",
                "Accept": "application/json",
            })
            r.raise_for_status()
            pj = r.json() or {}
            return (pj.get("_embedded") or {}).get("statuses") or []
    except Exception as e:
        log.warning("hh-autofill: cannot fetch pipeline %s: %s", pipeline_id, e)
        return []


async def autofill_hh_mapping() -> dict[str, str]:
    """
    Строит {amo_status_id: hh_code} по названиям стадий двух воронок (master/operator)
    и сохраняет в data/hh_mapping.json.
    """
    existing = hh_map_load().copy()
    result = existing.copy()

    pipelines: list[tuple[str, int | None]] = [
        ("master", getattr(settings, "AMO_PIPELINE_ID_MASTER", None)),
        ("operator", getattr(settings, "AMO_PIPELINE_ID_OPERATOR", None)),
    ]

    for label, pid in pipelines:
        if not pid:
            log.info("hh-autofill: pipeline %s is not configured — skip", label)
            continue

        statuses = await _fetch_pipeline_statuses(int(pid))
        if not statuses:
            log.info("hh-autofill: no statuses for pipeline %s (%s)", label, pid)
            continue

        found = 0
        for st in statuses:
            name = _norm_stage_name(st.get("name", ""))
            hh_code = _STAGE_NAME_TO_HH.get(name)
            if not hh_code:
                continue
            sid = str(st.get("id"))
            if not sid:
                continue
            result[sid] = hh_code
            found += 1

        log.info("hh-autofill: pipeline %s (%s): mapped %d statuses", label, pid, found)

    if result != existing:
        hh_map_set(result)
        log.info("hh-autofill: hh_mapping.json updated with %d keys", len(result))
    else:
        log.info("hh-autofill: mapping up-to-date (%d keys)", len(result))

    return result
