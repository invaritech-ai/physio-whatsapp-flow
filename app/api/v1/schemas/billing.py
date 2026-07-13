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
            raise ValueError(
                f"duration_minutes must be one of {sorted(SUPPORTED_PLAN_DURATIONS)}"
            )
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
            raise ValueError(
                f"duration_minutes must be one of {sorted(SUPPORTED_PLAN_DURATIONS)}"
            )
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
            raise ValueError(
                f"duration_minutes must be one of {sorted(SUPPORTED_PLAN_DURATIONS)}"
            )
        return self


class ClientPlanAssignmentsUpsertRequest(BaseModel):
    """Transactional upsert request for client plan assignments."""

    assignments: list[ClientPlanAssignmentUpsertItem] = Field(
        min_length=1, max_length=len(SUPPORTED_PLAN_DURATIONS)
    )

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
    """Client assignment response keyed by supported duration (str minutes)."""

    client_id: int
    # Keys are string forms of SUPPORTED_PLAN_DURATIONS (e.g. "15", "30", "45", "60");
    # value is None when the client has no active assignment for that duration.
    assignments: dict[str, ClientPlanAssignmentSummary | None]


class PaymentRecordCreateRequest(BaseModel):
    """Create request for recording received payment."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_id": 101,
                "source": "session_linked",
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
    source: Literal["session_linked", "admin_manual"] = "session_linked"
    session_id: int | None = Field(default=None, gt=0)
    amount_cents: int = Field(gt=0)
    currency: str = Field(default="HKD", min_length=3, max_length=8)
    method: Literal["cash", "electronic", "bank_transfer"]
    received_by_role: Literal["admin", "therapist"]
    received_by_name: str | None = Field(default=None, max_length=120)
    paid_at: datetime | None = None
    reference: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=2000)

class PaymentRecordItem(BaseModel):
    """Payment record response item."""

    id: int
    client_id: int
    source: Literal["session_linked", "admin_manual"]
    session_id: int | None
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
    updated_at: datetime
    created_at: datetime


class PaymentRecordCreateResponse(BaseModel):
    """Create-payment response with refreshed client financial snapshot."""

    payment: PaymentRecordItem
    financials: ClientFinancialResponse


class PaymentVerifyRequest(BaseModel):
    """Admin request to verify a pending payment."""

    auto_generate_receipt: bool = False
    amount_cents: int | None = Field(default=None, gt=0)
    diagnosis: str | None = Field(default=None, min_length=1, max_length=2000)
    diagnosis_preset_id: int | None = Field(default=None, gt=0)
    supervised_exercise: bool = True
    payment_mode: str | None = Field(default=None, min_length=1, max_length=120)
    send_whatsapp: bool = True


class PaymentVerifyResponse(BaseModel):
    """Response from verifying a payment, optionally with auto-generated receipt."""

    payment: PaymentRecordItem
    financials: ClientFinancialResponse
    receipt: "InvoiceDetailResponseRef | None" = None


class InvoiceDetailResponseRef(BaseModel):
    """Inline invoice detail for verify response (avoids circular import)."""

    id: int
    client_id: int
    session_id: int | None
    therapist_id: int | None
    service_type: str
    amount_cents: int
    currency: str
    description: str
    payment_mode: str | None
    diagnosis: str | None
    special_notes: str | None
    pdf_url: str | None
    status: str
    created_at: datetime
    whatsapp_sent: bool = False
    whatsapp_error: str | None = None


class BillingQueueItem(BaseModel):
    """Session-level billing queue row."""

    session_id: int
    client_id: int
    client_name: str | None
    therapist_id: int
    therapist_name: str | None
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    status: str
    currency: str
    expected_charge_cents: int | None
    paid_cents: int
    receipted_cents: int
    outstanding_cents: int
    needs_confirmation: bool
    default_receipt_amount_cents: int | None
    last_payment_at: datetime | None
    last_receipt_at: datetime | None


class BillingQueueResponse(BaseModel):
    """Paginated session-level billing queue."""

    items: list[BillingQueueItem]
    total: int
    limit: int
    offset: int
    has_more: bool
