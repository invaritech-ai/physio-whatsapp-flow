"""Pydantic schemas for admin client (patient) endpoints."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.api.v1.schemas.pricing import AssignedPlanSummary


class ClientListItem(BaseModel):
    """Client item for list/search responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    phone_e164: str
    email: str | None
    date_of_birth: date | None
    address: str | None
    preferred_therapist_id: int | None
    created_at: datetime
    updated_at: datetime


class ClientDetailResponse(ClientListItem):
    """Detailed client response."""


class ClientListResponse(BaseModel):
    """Paginated client list response."""

    items: list[ClientListItem]
    total: int
    limit: int
    offset: int
    has_more: bool


class ClientCreate(BaseModel):
    """Create client request payload."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "John Chan",
                "phone_e164": "+85291234567",
                "email": "john.chan@example.com",
                "date_of_birth": "1992-07-19",
                "address": "Flat 12A, Example Building, Kowloon, Hong Kong",
                "preferred_therapist_id": 12,
            }
        }
    )

    phone_e164: str = Field(..., pattern=r"^\+[1-9]\d{1,14}$")
    name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    date_of_birth: date | None = None
    address: str | None = Field(default=None, max_length=1000)
    preferred_therapist_id: int | None = Field(default=None, gt=0)


class ClientUpdate(BaseModel):
    """Update client request payload."""

    phone_e164: str | None = Field(default=None, pattern=r"^\+[1-9]\d{1,14}$")
    name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    date_of_birth: date | None = None
    address: str | None = Field(default=None, max_length=1000)
    preferred_therapist_id: int | None = Field(default=None, gt=0)


class ClientSessionListItem(BaseModel):
    """Session item for client session timeline."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    therapist_id: int
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


class ClientMessageListItem(BaseModel):
    """Message item for client message history."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    direction: str
    phone_e164: str
    body: str
    media_url: str | None
    twilio_sid: str | None
    created_at: datetime


class ClientFinancialResponse(BaseModel):
    """Financial summary for a client."""

    client_id: int
    currency: str
    total_paid_cents: int
    total_receipted_cents: int
    available_to_receipt_cents: int
    updated_at: datetime
