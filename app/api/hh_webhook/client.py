from __future__ import annotations

import re
from typing import Any

import httpx

HH_SUBS_URL = "https://api.hh.ru/webhook/subscriptions"


def _norm(s: str) -> str:
    """Нормализация названий событий: '.', '-', пробелы -> '_', lower."""
    return re.sub(r"[.\-\s]+", "_", s.strip().lower())


def _canon(u: str) -> str:
    """Канонизация URL для сравнения."""
    return (u or "").strip().rstrip("/")


async def _list_all_subs(client: httpx.AsyncClient, headers: dict[str, str]) -> list[dict]:
    """Возвращает все подписки с учётом пагинации (если она есть)."""
    subs: list[dict] = []
    page = 0
    per_page = 100
    while True:
        r = await client.get(
            HH_SUBS_URL,
            headers=headers,
            params={"page": page, "per_page": per_page},
            timeout=20,
        )
        r.raise_for_status()
        js: Any = r.json()
        items = js if isinstance(js, list) else js.get("items", [])
        subs.extend(items)
        if isinstance(js, list):
            break
        pages = js.get("pages")
        if not isinstance(pages, int) or page + 1 >= pages:
            break
        page += 1
    return subs


async def _find_sub_by_url(client: httpx.AsyncClient, headers: dict[str, str], url: str) -> dict | None:
    """Ищет подписку по точному URL (с канонизацией)."""
    cu = _canon(url)
    for it in await _list_all_subs(client, headers):
        if _canon(str(it.get("url", ""))) == cu:
            return it
    return None
