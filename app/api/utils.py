"""Utility helpers used across API modules."""

import re, html
from typing import Mapping


HASHTAG_RE = re.compile(r"(?i)(?<![\w#])#(?:мастер|оператор)\b")
_TAG_RE = re.compile(r"<[^>]+>")

def _plain_text(s: str) -> str:
    return _TAG_RE.sub(" ", html.unescape(s or ""))


def events_from_form(form: Mapping[str, str]) -> list[tuple[int, int]]:
    """Extract lead/status pairs from AmoCRM webhook form.

    Args:
        form: Mapping of form field names to their values.
    """
    keys = list(form.keys())
    idxs: set[int] = set()
    for k in keys:
        m = re.match(r"leads\[status\]\[(\d+)\]\[id\]$", k)
        if m:
            idxs.add(int(m.group(1)))
    events: list[tuple[int, int]] = []
    for i in sorted(idxs):
        lead_id = int(form.get(f"leads[status][{i}][id]", 0) or 0)
        status_id = int(form.get(f"leads[status][{i}][status_id]", 0) or 0)
        if lead_id and status_id:
            events.append((lead_id, status_id))
    return events


def route_kind(*, desc: str = "", raw: str = "") -> str:
    """Return pipeline kind based on hashtags in vacancy description or raw text."""
    blob = " ".join([_plain_text(desc), (raw or "")])
    m = HASHTAG_RE.search(blob)
    if not m:
        return "ignore"
    all_tags = [t.group(0).lower() for t in HASHTAG_RE.finditer(blob)]
    if any("мастер" in t for t in all_tags):
        return "master"
    if any("оператор" in t for t in all_tags):
        return "operator"
    return "ignore"


_REFUSAL_NAMES = {
    "discard_by_employer": "Не подходит",
    "discard_by_applicant": "Кандидат отказался",
    "rejected_by_applicant": "Кандидат отказался",
    "discard_no_interaction": "Не выходит на связь",
    "discard_vacancy_closed": "Вакансия закрыта",
    "discard_to_other_vacancy": "Перевод на другую вакансию",
}


def is_refusal_code(code: str | None) -> bool:
    """Return ``True`` if the given code represents a refusal."""
    if not code:
        return False
    return code.startswith("discard") or code.startswith("reject")


def refusal_text(code: str | None) -> str | None:
    """Map a refusal code to its human‑readable description."""
    return _REFUSAL_NAMES.get(code or "")


# Текст причины (в Amo CF) -> код HH
REFUSAL_TEXT_TO_HH = {
    "не подходит": "discard_by_employer",
    "кандидат отказался": "discard_by_applicant",
    "не выходит на связь": "discard_no_interaction",
    "вакансия закрыта": "discard_vacancy_closed",
    "перевод на другую вакансию": "discard_to_other_vacancy",
}


def norm_reason(s: str | None) -> str:
    """Normalize reason text by stripping whitespace and lowering case."""
    return (s or "").strip().lower()


__all__ = [
    "events_from_form",
    "route_kind",
    "is_refusal_code",
    "refusal_text",
    "REFUSAL_TEXT_TO_HH",
    "norm_reason",
]
