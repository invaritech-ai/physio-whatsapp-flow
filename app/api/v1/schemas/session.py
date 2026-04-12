"""Pydantic schemas for therapist session endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.pricing import AssignedPlanSummary


class SessionListItem(BaseModel):
    """Response schema for a session in a list view."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    client_name: str | None
    client_phone: str | None
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    status: str
    expected_charge_cents: int | None = None
    expected_charge_currency: str | None = None
    assigned_plan: AssignedPlanSummary | None = None
    has_clinical_note: bool = False
    clinical_note_preview: str | None = None


class SessionListResponse(BaseModel):
    """Paginated envelope for therapist sessions list."""

    items: list[SessionListItem]
    total: int
    limit: int
    offset: int
    has_more: bool


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
    expected_charge_cents: int | None = None
    expected_charge_currency: str | None = None
    assigned_plan: AssignedPlanSummary | None = None
    calendly_event_uri: str | None
    created_at: datetime


class SessionSummary(BaseModel):
    """Response schema for session summary counts."""

    upcoming: int
    completed: int
    cancelled: int
    no_show: int
    next_session: SessionListItem | None


class SessionStatusUpdateRequest(BaseModel):
    """Mutation payload for therapist session status updates."""

    status: str = Field(
        pattern="^(scheduled|started|completed|cancelled|no_show)$",
    )
    duration_minutes: int | None = Field(default=None, gt=0)


class SessionStatusUpdateResponse(BaseModel):
    """Response payload for therapist session status updates."""

    session_id: int
    status: str
    duration_minutes: int
    updated_at: datetime


class TherapistRecordPaymentRequest(BaseModel):
    """Therapist records payment collected for a completed session."""

    amount_cents: int = Field(gt=0)
    method: Literal["cash", "electronic", "bank_transfer"]
    notes: str | None = Field(default=None, max_length=2000)


class TherapistRecordPaymentResponse(BaseModel):
    """Response after therapist records a payment."""

    payment_id: int
    session_id: int
    amount_cents: int
    currency: str
    method: str
    paid_at: datetime
