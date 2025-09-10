from __future__ import annotations

"""Pydantic schemas describing tasks published to RabbitMQ."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class EventBase(BaseModel):
    """Common fields for all queue events."""

    platform: str
    action: str
    payload: BaseModel
    msg_key: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class LeadCreatedPayload(BaseModel):
    """Payload for creating a lead in amoCRM."""

    lead_body: list[dict[str, Any]]
    ts: int


class LeadCreated(EventBase):
    """Event requesting creation of a lead in amoCRM."""

    action: Literal["amo_create_lead"] = "amo_create_lead"
    payload: LeadCreatedPayload


class SendMessagePayload(BaseModel):
    """Payload for sending a message to a candidate."""

    external_id: str
    text: str
    owner_id: str | None = None


class SendMessage(EventBase):
    """Event requesting to send a message on an external platform."""

    action: Literal["send_message"] = "send_message"
    payload: SendMessagePayload


class UpdateStatusPayload(BaseModel):
    """Payload for updating status on a platform or in amoCRM."""

    external_id: str | None = None
    target_state: str | None = None
    action_id: str | None = None
    lead_id: int | None = None
    status_id: int | None = None
    owner_id: str | None = None


class UpdateStatus(EventBase):
    """Event requesting a status update."""

    action: Literal["set_state", "amo_update_status"]
    payload: UpdateStatusPayload


__all__ = [
    "LeadCreated",
    "LeadCreatedPayload",
    "SendMessage",
    "SendMessagePayload",
    "UpdateStatus",
    "UpdateStatusPayload",
]
