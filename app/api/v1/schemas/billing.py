"""Schemas for admin billing plans and payments."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.v1.schemas.client import ClientFinancialResponse
from app.services.pricing import SUPPORTED_PLAN_DURATIONS


class BillingPlanCreate(BaseModel):
    """Create request for a billing plan."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Regular 45",
                "duration_minutes": 45,
                "amount_cents": 100000,
                "currency": "HKD",
                "is_active": True,
            }
        }
    )

    name: str = Field(min_length=1, max_length=120)
    duration_minutes: int
    amount_cents: int = Field(gt=0)
    currency: str = Field(default="HKD", min_length=3, max_length=8)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_duration(self) -> "BillingPlanCreate":
        if self.duration_minutes not in SUPPORTED_PLAN_DURATIONS:
            raise ValueError("duration_minutes must be one of 30 or 45 for v1")
        return self


class BillingPlanUpdate(BaseModel):
    """Patch request for a billing plan."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    duration_minutes: int | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_duration(self) -> "BillingPlanUpdate":
        if self.duration_minutes is not None and self.duration_minutes not in SUPPORTED_PLAN_DURATIONS:
            raise ValueError("duration_minutes must be one of 30 or 45 for v1")
        return self


class BillingPlanResponse(BaseModel):
    """Billing plan response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    duration_minutes: int
    amount_cents: int
    currency: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ClientPlanAssignmentUpsertItem(BaseModel):
    """One plan-assignment operation for a duration slot."""

    duration_minutes: int
    billing_plan_id: int | None = Field(default=None, gt=0)
    effective_from: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_duration(self) -> "ClientPlanAssignmentUpsertItem":
        if self.duration_minutes not in SUPPORTED_PLAN_DURATIONS:
            raise ValueError("duration_minutes must be one of 30 or 45 for v1")
        return self


class ClientPlanAssignmentsUpsertRequest(BaseModel):
    """Transactional upsert request for client plan assignments."""

    assignments: list[ClientPlanAssignmentUpsertItem] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_unique_durations(self) -> "ClientPlanAssignmentsUpsertRequest":
        durations = [a.duration_minutes for a in self.assignments]
        if len(durations) != len(set(durations)):
            raise ValueError("duplicate duration_minutes entries are not allowed")
        return self


class ClientPlanAssignmentSummary(BaseModel):
    """Expanded client plan assignment summary."""

    plan_id: int
    plan_name: str
    duration_minutes: int
    amount_cents: int
    currency: str
    effective_from: datetime
    notes: str | None = None
    is_active: bool


class ClientPlanAssignmentsResponse(BaseModel):
    """Deterministic client assignment response for duration 30 and 45."""

    client_id: int
    duration_30: ClientPlanAssignmentSummary | None
    duration_45: ClientPlanAssignmentSummary | None


class PaymentRecordCreateRequest(BaseModel):
    """Create request for recording received payment."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_id": 101,
                "session_id": 501,
                "amount_cents": 75000,
                "currency": "HKD",
                "method": "electronic",
                "received_by_role": "therapist",
                "received_by_name": "Dr. Ying Cheng",
                "paid_at": "2026-02-19T10:30:00Z",
                "reference": "FPS-123456",
                "notes": "Patient paid after session",
            }
        }
    )

    client_id: int = Field(gt=0)
    session_id: int = Field(gt=0)
    amount_cents: int = Field(gt=0)
    currency: str = Field(default="HKD", min_length=3, max_length=8)
    method: Literal["cash", "electronic"]
    received_by_role: Literal["admin", "therapist"]
    received_by_name: str | None = Field(default=None, max_length=120)
    paid_at: datetime | None = None
    reference: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=2000)


class PaymentRecordItem(BaseModel):
    """Payment record response item."""

    id: int
    client_id: int
    session_id: int
    amount_cents: int
    currency: str
    method: str
    status: str
    received_by_role: str | None
    received_by_name: str | None
    paid_at: datetime | None
    reference: str | None
    notes: str | None
    recorded_by_user_id: int
    created_at: datetime


class PaymentRecordCreateResponse(BaseModel):
    """Create-payment response with refreshed client financial snapshot."""

    payment: PaymentRecordItem
    financials: ClientFinancialResponse
