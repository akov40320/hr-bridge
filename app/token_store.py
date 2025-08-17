import time
from typing import TypedDict
from sqlalchemy import select, insert, update
from app.db import get_session
from app.models import Token


class TokenData(TypedDict):
    access_token: str
    refresh_token: str
    expires_at: int


class DbTokenStore:
    def __init__(self, service: str):
        self.service = service

    async def load(self) -> TokenData:
        async with get_session() as s:
            row = (await s.execute(select(Token).where(Token.service == self.service))).scalar_one_or_none()
            if not row:
                raise RuntimeError(f"Token for {self.service} not found")
            return {"access_token": row.access_token, "refresh_token": row.refresh_token, "expires_at": row.expires_at}

    async def save(self, data: TokenData) -> None:
        async with get_session() as s:
            row = (await s.execute(select(Token).where(Token.service == self.service))).scalar_one_or_none()
            if row:
                await s.execute(
                    update(Token).where(Token.service == self.service).values(
                        access_token=data["access_token"],
                        refresh_token=data["refresh_token"],
                        expires_at=data["expires_at"],
                    )
                )
            else:
                await s.execute(
                    insert(Token).values(
                        service=self.service,
                        access_token=data["access_token"],
                        refresh_token=data["refresh_token"],
                        expires_at=data["expires_at"],
                    )
                )
            await s.commit()

    async def will_expire_soon(self, margin_sec: int = 120) -> bool:
        try:
            data = await self.load()
            return time.time() > data["expires_at"] - margin_sec
        except Exception:
            return True
