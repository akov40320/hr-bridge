import json, os
from threading import Lock
from typing import Optional

PATH = "data/hh_mapping.json"
_cache: dict[str, str] = {}
_lock = Lock()


def _ensure_dir():
    os.makedirs("data", exist_ok=True)


def load() -> dict[str, str]:
    _ensure_dir()
    if os.path.exists(PATH):
        with open(PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    return {}


def get(status_id: int) -> Optional[str]:
    with _lock:
        if not _cache:
            _cache.update(load())
        return _cache.get(str(status_id))


def set_all(mapping: dict[str, str]) -> dict[str, str]:
    _ensure_dir()
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    new_data = mapping.copy()
    with _lock:
        _cache.clear()
        _cache.update(new_data)
    return new_data
