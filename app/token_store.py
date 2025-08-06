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
        if not os.path.exists(self.path):
            raise RuntimeError("Token file not found")
        with open(self.path, "r", encoding="utf-8-sig") as f:
            return json.load(f)

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
