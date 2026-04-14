"""Pydantic schemas for invoice endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

InvoiceServiceType = Literal["standard", "supervised_physio", "other"]


class InvoiceListItem(BaseModel):
    """Invoice item returned by admin invoice list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    session_id: int | None
    therapist_id: int | None
    service_type: InvoiceServiceType
    trainer_name: str | None = None
    reference_note: str | None = None
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
    whatsapp_sent: bool = False
    whatsapp_error: str | None = None


class InvoicePdfUrlResponse(BaseModel):
    """Fresh downloadable PDF URL for an existing invoice."""

    invoice_id: int
    pdf_url: str


class InvoiceGenerateRequest(BaseModel):
    """Admin request payload to generate a session-linked or sessionless invoice."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_id": 101,
                "session_id": 501,
                "manual_session_start_at": None,
                "therapist_id": 55,
                "service_type": "standard",
                "trainer_name": None,
                "reference_note": None,
                "amount_cents": 65000,
                "currency": "HKD",
                "description": "Physio session invoice",
                "payment_mode": "cash",
                "diagnosis_preset_id": None,
                "diagnosis": "Bilateral plantar fasciitis",
                "special_note_preset_id": None,
                "special_notes": "Please submit to insurer within 30 days.",
                "send_whatsapp": True,
            }
        }
    )

    client_id: int = Field(gt=0)
    session_id: int | None = Field(default=None, gt=0)
    manual_session_start_at: datetime | None = None
    therapist_id: int | None = Field(default=None, gt=0)
    service_type: InvoiceServiceType = Field(default="standard")
    trainer_name: str | None = Field(default=None, min_length=1, max_length=120)
    reference_note: str | None = Field(default=None, min_length=1, max_length=2000)
    amount_cents: int | None = Field(default=None, gt=0)
    currency: str = Field(default="HKD", min_length=3, max_length=8)
    description: str = Field(min_length=1, max_length=2000)
    payment_mode: str | None = Field(default=None, min_length=1, max_length=120)
    diagnosis_preset_id: int | None = Field(default=None, gt=0)
    diagnosis: str | None = Field(default=None, min_length=1, max_length=2000)
    special_note_preset_id: int | None = Field(default=None, gt=0)
    special_notes: str | None = Field(default=None, min_length=1, max_length=4000)
    send_whatsapp: bool = Field(default=True)


class ReceiptingSummaryReceiptItem(BaseModel):
    """Receipt item in admin receipting summary."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int | None
    service_type: InvoiceServiceType
    amount_cents: int
    currency: str
    description: str
    created_at: datetime


class ReceiptingSummaryResponse(BaseModel):
    """Running receipting totals and recent receipt ledger for a client."""

    client_id: int
    currency: str
    total_paid_cents: int
    total_receipted_cents: int
    claimable_balance_cents: int
    receipts: list[ReceiptingSummaryReceiptItem]
    limit: int
    offset: int
    has_more: bool


class SendWhatsAppResponse(BaseModel):
    """Response from manually sending an invoice via WhatsApp."""

    invoice_id: int
    whatsapp_sent: bool
    whatsapp_error: str | None = None


class TherapistInvoiceListItem(InvoiceListItem):
    """Therapist-scoped invoice list item."""

    client_name: str | None
    client_phone_e164: str


class TherapistInvoiceDetailResponse(TherapistInvoiceListItem):
    """Therapist-scoped invoice detail response."""

    issued_by_user_id: int
