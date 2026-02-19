"""Pydantic schemas for therapist patient endpoints."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class TherapistPatientListItem(BaseModel):
    """Therapist-scoped patient list item."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    phone_e164: str
    email: str | None
    date_of_birth: date | None
    address: str | None
    session_count: int
    upcoming_session_count: int
    last_session_at: datetime | None
    next_session_at: datetime | None


class TherapistPatientDetailResponse(BaseModel):
    """Therapist-scoped patient detail."""

    id: int
    name: str | None
    phone_e164: str
    email: str | None
    date_of_birth: date | None
    address: str | None
    session_count: int
    completed_session_count: int
    upcoming_session_count: int
    last_session_at: datetime | None
    next_session_at: datetime | None


class TherapistPatientSessionItem(BaseModel):
    """Session item under therapist patient detail."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    status: str
    source: str
    charge_amount_cents: int | None
    currency: str
