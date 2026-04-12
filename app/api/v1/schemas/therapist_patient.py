"""Pydantic schemas for therapist patient endpoints."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.api.v1.schemas.pricing import AssignedPlanSummary


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
    plan_30: AssignedPlanSummary | None = None
    plan_45: AssignedPlanSummary | None = None


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
    expected_charge_cents: int | None = None
    expected_charge_currency: str | None = None
    assigned_plan: AssignedPlanSummary | None = None
    has_clinical_note: bool = False
    clinical_note_preview: str | None = None
    clinical_note_saved_at: datetime | None = None
