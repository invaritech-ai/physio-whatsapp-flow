"""Pydantic schemas for therapist session endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionListItem(BaseModel):
    """Response schema for a session in a list view."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    client_name: str | None
    client_phone: str | None
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    status: str


class SessionDetail(BaseModel):
    """Response schema for session detail view."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    client_name: str | None
    client_phone: str | None
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    status: str
    source: str
    charge_amount_cents: int | None
    currency: str
    calendly_event_uri: str | None
    created_at: datetime


class SessionSummary(BaseModel):
    """Response schema for session summary counts."""

    upcoming: int
    completed: int
    cancelled: int
    no_show: int
    next_session: SessionListItem | None
