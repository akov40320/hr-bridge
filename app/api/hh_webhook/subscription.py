from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings

from .client import _norm

log = logging.getLogger(__name__)

EVENT_MAP: dict[str, str] = {
    "negotiation_created": "NEW_NEGOTIATION_VACANCY",
    "negotiation_status_changed": "NEGOTIATION_EMPLOYER_STATE_CHANGE",
    # "message_created": "NEW_NEGOTIATION_MESSAGE",
}


def _target_url() -> str:
    s = get_settings()
    return (getattr(s, "HH_WEBHOOK_URL", "") or "").strip()


def _keyify_action(x: dict) -> tuple:
    """Ключ для сравнения action (тип + settings)."""
    return (x.get("type"), tuple(sorted((x.get("settings") or {}).items())))


def _same_actions(a_list: list[dict], b_list: list[dict]) -> bool:
    """Равенство множеств actions без учёта порядка."""
    return set(map(_keyify_action, a_list)) == set(map(_keyify_action, b_list))


def _actions() -> list[dict]:
    """Собирает actions из ENV HH_WEBHOOK_EVENTS."""
    s = get_settings()
    raw = (getattr(s, "HH_WEBHOOK_EVENTS", "") or "").strip()
    tokens = [t for t in (x.strip() for x in raw.split(",")) if t] or ["negotiation.created"]

    actions: list[dict] = []
    invalid: list[str] = []

    for token in tokens:
        key = _norm(token)
        type_name = EVENT_MAP.get(key)
        if not type_name:
            invalid.append(token)
            continue
        if type_name == "NEW_NEGOTIATION_VACANCY":
            actions.append({"type": type_name, "settings": {"vacancies_only_mine": False}})
        else:
            actions.append({"type": type_name})

    if invalid:
        log.warning("HH webhook: проигнорированы неподдерживаемые события: %s", ",".join(invalid))
    return actions
