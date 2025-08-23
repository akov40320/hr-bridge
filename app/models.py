"""Shared Pydantic models used throughout the service."""

from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict


class Applicant(BaseModel):
    """Applicant details parsed from incoming payload."""

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    phone: str | None = None
    city: str | None = None

    model_config = ConfigDict(extra="allow")


class IncomingPayload(BaseModel):
    """Normalized incoming payload from external platforms."""

    platform: str
    owner_id: str | None = None
    vacancy_id: str | None = None
    vacancy_title: str = ""
    vacancy_desc: str = ""
    applicant: Applicant
    raw_text: str | None = None
    kind: str | None = None

    model_config = ConfigDict(extra="allow")


class AvitoPayload(BaseModel):
    """Raw Avito webhook payload after initial extraction."""

    chat_id: str = Field(..., min_length=1)
    item_id: str | None = None
    item_title: str = "Отклик Avito"
    item_description: str = ""
    applicant_id: str | None = None
    text: str = ""
    owner_id: str | None = None

    model_config = ConfigDict(extra="allow")


__all__ = ["IncomingPayload", "Applicant", "AvitoPayload"]
