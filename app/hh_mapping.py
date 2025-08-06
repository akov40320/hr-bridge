import json, os
from typing import Optional

PATH = "data/hh_mapping.json"
_cache: dict[str, str] = {}


def _ensure_dir():
    os.makedirs("data", exist_ok=True)


def load() -> dict[str, str]:
    global _cache
    _ensure_dir()
    if os.path.exists(PATH):
        with open(PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f) or {}
    else:
        _cache = {}
    return _cache


def get(status_id: int) -> Optional[str]:
    if not _cache:
        load()
    return _cache.get(str(status_id))


def set_all(mapping: dict[str, str]) -> dict[str, str]:
    _ensure_dir()
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    return load()
