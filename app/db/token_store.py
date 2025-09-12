"""Утилиты для хранения и получения OAuth‑токенов."""

import time
from typing import Optional, TypedDict

from sqlalchemy import insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from .db import get_session
from .models import Token


class TokenData(TypedDict):
    """Информация об OAuth‑токене."""

    access_token: str
    refresh_token: str
    expires_at: int


class DbTokenStore:
    """Store and retrieve tokens for a specific service and owner.

    Ключ токена = (service, owner_id)
      - HH:    service="hh",    owner_id="<employer_id>"
      - Avito: service="avito", owner_id="<account_id>"
      - Amo:   service="amo",   owner_id=None
    """

    def __init__(self, service: str, owner_id: Optional[str] = None):
        """Initialize token storage for the given service and owner."""

        self.service = service
        self.owner_id = owner_id

    async def load(self) -> TokenData:
        """Load token data from the database."""

        async with get_session() as s:
            q = select(Token).where(Token.service == self.service)
            if self.owner_id is None:
                q = q.where(Token.owner_id.is_(None))
            else:
                q = q.where(Token.owner_id == self.owner_id)
            row = (await s.execute(q)).scalar_one_or_none()
            if not row:
                raise RuntimeError(
                    f"Token for service={self.service} owner={self.owner_id or '-'} not found"
                )
            return {
                "access_token": row.access_token,
                "refresh_token": row.refresh_token,
                "expires_at": row.expires_at,
            }

    async def save(self, data: TokenData) -> None:
        """Save token data into the database."""

        async with get_session() as s:
            q = select(Token).where(Token.service == self.service)
            if self.owner_id is None:
                q = q.where(Token.owner_id.is_(None))
            else:
                q = q.where(Token.owner_id == self.owner_id)
            row = (await s.execute(q)).scalar_one_or_none()

            values = {
                "service": self.service,
                "owner_id": self.owner_id,
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
                "expires_at": data["expires_at"],
            }

            if row:
                # Выполняем update только при наличии изменений
                has_changes = any(getattr(row, k) != v for k, v in values.items())
                if not has_changes:
                    return
                await s.execute(
                    update(Token)
                    .where(
                        Token.service == self.service,
                        Token.owner_id.is_(None)
                        if self.owner_id is None
                        else Token.owner_id == self.owner_id,
                    )
                    .values(**values)
                )
            else:
                await s.execute(insert(Token).values(**values))
            await s.commit()

    async def will_expire_soon(self, margin_sec: int = 120) -> bool:
        """Проверить, истекает ли токен в течение ``margin_sec`` секунд."""

        try:
            data = await self.load()
            return time.time() > data["expires_at"] - margin_sec
        except (RuntimeError, SQLAlchemyError):
            return True

    @staticmethod
    async def list_owners(service: str) -> list[str]:
        """Список владельцев, у которых есть токены для указанного сервиса."""

        async with get_session() as s:
            rows = (
                await s.execute(select(Token.owner_id).where(Token.service == service))
            ).all()
            return [r[0] for r in rows if r[0]]
