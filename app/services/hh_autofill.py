"""Mapping utility for the HH autofill service.

The module fetches Amo CRM pipeline statuses and builds a mapping to
HeadHunter status codes. The resulting mapping is stored for later reuse.
"""

import re
import logging
from pathlib import Path

import httpx
import yaml  # type: ignore[import-untyped]
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.token_store import DbTokenStore
from app.services.hh_mapping import load as hh_map_load, set_all as hh_map_set

log = logging.getLogger(__name__)


def _norm_stage_name(s: str) -> str:
    s = (s or "").strip().lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", s)


MAPPING_FILE = Path(__file__).resolve().parents[2] / "data" / "hh_stage_mapping.yaml"


def _load_stage_mapping(path: Path) -> dict[str, str]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {str(k): str(v) for k, v in data.items()}
    except FileNotFoundError:
        log.warning("hh-autofill: mapping file %s not found", path)
    except yaml.YAMLError as e:
        log.warning("hh-autofill: cannot parse mapping file %s: %s", path, e)
    return {}


_STAGE_NAME_TO_HH: dict[str, str] = {}


def reload_stage_mapping(path: Path | None = None) -> None:
    """Reload stage mapping from YAML file."""
    global _STAGE_NAME_TO_HH  # pylint: disable=global-statement
    _STAGE_NAME_TO_HH = _load_stage_mapping(path or MAPPING_FILE)


reload_stage_mapping()


async def _fetch_pipeline_statuses(
    pipeline_id: int,
    client: httpx.AsyncClient,
) -> list[dict]:
    try:
        tok = await DbTokenStore("amo").load()
    except (RuntimeError, SQLAlchemyError) as e:
        log.warning("hh-autofill: no amo token: %s", e)
        return []

    s = get_settings()
    url = s.AMO_BASE_URL.rstrip("/") + f"/api/v4/leads/pipelines/{pipeline_id}"
    try:
        r = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {tok['access_token']}",
                "Accept": "application/json",
            },
            timeout=20,
        )
        r.raise_for_status()
        pj = r.json() or {}
        return (pj.get("_embedded") or {}).get("statuses") or []
    except (httpx.HTTPError, ValueError) as e:
        log.warning("hh-autofill: cannot fetch pipeline %s: %s", pipeline_id, e)
        return []


async def autofill_hh_mapping(client: httpx.AsyncClient) -> dict[str, str]:
    """
    Строит {amo_status_id: hh_code} по названиям стадий двух воронок
    (master/operator) и сохраняет их в таблицу ``hh_mapping``.
    """
    existing = await hh_map_load()
    result = existing.copy()

    s = get_settings()
    pipelines: list[tuple[str, int | None]] = [
        ("master", getattr(s, "AMO_PIPELINE_ID_MASTER", None)),
        ("operator", getattr(s, "AMO_PIPELINE_ID_OPERATOR", None)),
    ]

    for label, pid in pipelines:
        if not pid:
            log.info("hh-autofill: pipeline %s is not configured — skip", label)
            continue

        statuses = await _fetch_pipeline_statuses(int(pid), client)
        if not statuses:
            log.info("hh-autofill: no statuses for pipeline %s (%s)", label, pid)
            continue

        found = 0
        for st in statuses:
            sid = str(st.get("id"))
            if not sid:
                continue
            result.pop(sid, None)
            name = _norm_stage_name(st.get("name", ""))
            hh_code = _STAGE_NAME_TO_HH.get(name)
            if not hh_code:
                continue
            result[sid] = hh_code
            found += 1

        log.info("hh-autofill: pipeline %s (%s): mapped %d statuses", label, pid, found)

    if result != existing:
        await hh_map_set(result)
        log.info("hh-autofill: hh_mapping table updated with %d keys", len(result))
    else:
        log.info("hh-autofill: mapping up-to-date (%d keys)", len(result))

    return result
