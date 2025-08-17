from __future__ import annotations
import json, time, os
from typing import TypedDict


class TokenData(TypedDict):
    access_token: str
    refresh_token: str
    expires_at: int


class FileTokenStore:
    def __init__(self, path: str = "secrets/amo_token.json"):
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def load(self) -> TokenData:
        # 1) Пытаемся из файла
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        # 2) Фоллбек на ENV (для Render/первого запуска)
        at = os.getenv("AMO_ACCESS_TOKEN")
        rt = os.getenv("AMO_REFRESH_TOKEN")
        ea = os.getenv("AMO_EXPIRES_AT")
        if at and rt and ea:
            return TokenData(access_token=at, refresh_token=rt, expires_at=int(ea))
        # 3) Совсем нет токена
        raise RuntimeError("Token file not found and env vars missing")

    def save(self, data: TokenData) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def will_expire_soon(self, margin_sec: int = 120) -> bool:
        try:
            data = self.load()
            return time.time() > data["expires_at"] - margin_sec
        except Exception:
            return True
