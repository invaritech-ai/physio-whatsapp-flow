"""Schemas for admin session management endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.api.v1.schemas.pricing import AssignedPlanSummary


class AdminSessionListItem(BaseModel):
    """Single session row for admin sessions list."""

    id: int
    client_id: int
    client_name: str | None
    therapist_id: int
    therapist_name: str | None
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


class AdminSessionListResponse(BaseModel):
    """Paginated envelope for admin sessions list."""

    items: list[AdminSessionListItem]
    total: int
    limit: int
    offset: int
    has_more: bool


class AdminSessionDetailResponse(BaseModel):
    """Detailed admin session payload."""

    id: int
    client_id: int
    client_name: str | None
    therapist_id: int
    therapist_name: str | None
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
    calendly_invitee_uri: str | None
    created_at: datetime
    updated_at: datetime


class AdminSessionUpdateRequest(BaseModel):
    """Admin session mutation payload."""

    status: str | None = Field(
        default=None,
        pattern="^(scheduled|started|completed|cancelled|no_show)$",
    )
    billing_plan_id: int | None = Field(default=None, gt=0)
    plan_effective_from: datetime | None = None
    plan_notes: str | None = Field(default=None, max_length=1000)
