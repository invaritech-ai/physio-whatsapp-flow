"""Schemas for Calendly operational queue/feed endpoints (Phase E)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CalendlyQueueItem(BaseModel):
    id: int
    event_type: Literal["invitee.created", "invitee.canceled", "invitee.rescheduled"]
    calendly_event_uri: str | None
    calendly_invitee_uri: str | None
    client_id: int | None
    client_name: str | None
    therapist_id: int | None
    therapist_name: str | None
    start_time: datetime | None
    end_time: datetime | None
    status: Literal["new", "acknowledged", "resolved"]
    created_at: datetime


class CalendlyQueueListResponse(BaseModel):
    items: list[CalendlyQueueItem]
    total: int
    limit: int
    offset: int
    has_more: bool


class CalendlyQueueTransitionResponse(BaseModel):
    id: int
    status: Literal["acknowledged", "resolved"]
    updated_at: datetime


class TherapistCalendlyFeedItem(BaseModel):
    id: int
    event_type: Literal["created", "canceled", "rescheduled"]
    session_id: int | None
    client_id: int | None
    client_name: str | None
    start_time: datetime | None
    end_time: datetime | None
    status: Literal["new", "seen"]
    created_at: datetime


class TherapistCalendlyFeedListResponse(BaseModel):
    items: list[TherapistCalendlyFeedItem]
    total: int
    limit: int
    offset: int
    has_more: bool


class TherapistCalendlyFeedSeenResponse(BaseModel):
    id: int
    status: Literal["seen"]
    updated_at: datetime
