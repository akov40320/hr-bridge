"""Модели базы данных приложения HR Bridge."""
# pylint: disable=trailing-newlines

from __future__ import annotations

# pylint: disable=too-few-public-methods

from datetime import datetime

from typing import Any
from sqlalchemy import BigInteger, Text, Integer, TIMESTAMP, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from .base import Base


class Token(Base):
    """OAuth‑токены внешних сервисов."""

    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(
        Text, nullable=False, index=True
    )  # "hh" | "avito" | "amo" ...
    owner_id: Mapped[str | None] = mapped_column(
        Text, nullable=True, index=True
    )  # HH: employer_id; Avito: account_id

    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
        onupdate=func.now(),  # pylint: disable=not-callable
    )
    __table_args__ = (
        UniqueConstraint("service", "owner_id", name="ux_tokens_service_owner"),
    )


class LeadLink(Base):
    """Связывает внутренние сделки с записями внешних платформ."""

    __tablename__ = "lead_links"

    lead_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    platform: Mapped[str] = mapped_column(Text, nullable=False)  # "hh" | "avito"
    owner_id: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # HH employer_id / Avito account_id

    vacancy_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
    )


class TgLink(Base):
    """Связи пользователей Telegram со сделками и диалогами."""

    __tablename__ = "tg_links"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bot_kind: Mapped[str] = mapped_column(Text, primary_key=True)  # "master" | "operator"
    lead_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(Text)  # для AmoChats
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
        onupdate=func.now(),  # pylint: disable=not-callable
    )


class TgSurvey(Base):
    """Ответы опроса, собранные через Telegram‑ботов."""

    __tablename__ = "tg_surveys"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bot_kind: Mapped[str] = mapped_column(Text, primary_key=True)  # "master" | "operator"
    lead_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)

    step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0..2
    city: Mapped[str | None] = mapped_column(Text)
    experience: Mapped[str | None] = mapped_column(Text)
    time_pref: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
        onupdate=func.now(),  # pylint: disable=not-callable
    )


class EventDedup(Base):
    """Учёт обработанных событий для предотвращения дублей."""

    __tablename__ = "events_dedup"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
    )


class Task(Base):
    """Фоновые задачи с идемпотентной семантикой обработки."""

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(Text, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
        onupdate=func.now(),  # pylint: disable=not-callable
    )


class HhMapping(Base):
    """Сопоставление ID статусов AmoCRM и кодов состояний HeadHunter."""

    __tablename__ = "hh_mapping"

    amo_status_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    hh_code: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
        onupdate=func.now(),  # pylint: disable=not-callable
    )

