"""Pydantic schemas for invoice endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InvoiceListItem(BaseModel):
    """Invoice item returned by admin invoice list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    session_id: int | None
    amount_cents: int
    currency: str
    description: str
    payment_mode: str | None = None
    diagnosis: str | None = None
    special_notes: str | None = None
    pdf_url: str | None
    status: str
    created_at: datetime


class InvoiceDetailResponse(InvoiceListItem):
    """Admin invoice detail response."""

    issued_by_user_id: int


class InvoiceGenerateRequest(BaseModel):
    """Admin request payload to generate a single-session invoice."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_id": 101,
                "session_id": 501,
                "amount_cents": 65000,
                "currency": "HKD",
                "description": "Physio session invoice",
                "payment_mode": "cash",
                "diagnosis": "Bilateral plantar fasciitis",
                "special_notes": "Please submit to insurer within 30 days.",
            }
        }
    )

    client_id: int = Field(gt=0)
    session_id: int = Field(gt=0)
    amount_cents: int | None = Field(default=None, gt=0)
    currency: str = Field(default="HKD", min_length=3, max_length=8)
    description: str = Field(min_length=1, max_length=2000)
    payment_mode: str | None = Field(default=None, min_length=1, max_length=120)
    diagnosis: str | None = Field(default=None, min_length=1, max_length=2000)
    special_notes: str | None = Field(default=None, min_length=1, max_length=4000)


class TherapistInvoiceListItem(InvoiceListItem):
    """Therapist-scoped invoice list item."""

    client_name: str | None
    client_phone_e164: str


class TherapistInvoiceDetailResponse(TherapistInvoiceListItem):
    """Therapist-scoped invoice detail response."""

    issued_by_user_id: int
