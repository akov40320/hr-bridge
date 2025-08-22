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


__all__ = ["IncomingPayload", "Applicant"]
