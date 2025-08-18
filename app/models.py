from datetime import datetime

from sqlalchemy import BigInteger, Text, Integer, JSON, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from sqlalchemy.sql import func


class Token(Base):
    __tablename__ = "tokens"
    service: Mapped[str] = mapped_column(Text, primary_key=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LeadLink(Base):
    __tablename__ = "lead_links"
    lead_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    vacancy_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class TgLink(Base):
    __tablename__ = "tg_links"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bot_kind: Mapped[str] = mapped_column(Text, primary_key=True)  # "master" | "operator"
    lead_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(Text)  # для AmoChats, появится позже
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TgSurvey(Base):
    __tablename__ = "tg_surveys"
    # одна активная сессия на (user_id, bot_kind)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bot_kind: Mapped[str] = mapped_column(Text, primary_key=True)  # "master" | "operator"
    lead_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)

    step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0..2
    city: Mapped[str | None] = mapped_column(Text)
    experience: Mapped[str | None] = mapped_column(Text)
    time_pref: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

class EventDedup(Base):
    __tablename__ = "events_dedup"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), index=True
    )