from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class PaymentRecord(SQLModel, table=True):
    """Record of payment received for a session."""

    __tablename__ = "payment_record"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="session.id", index=True)
    amount_cents: int  # Amount in cents (e.g., 50000 = HKD 500.00)
    currency: str = Field(default="HKD")
    payment_method: str  # e.g., "cash", "credit_card", "fps", "bank_transfer"
    status: str = Field(default="pending")  # pending|confirmed|rejected
    received_by_role: str | None = Field(default=None, max_length=20)  # admin|therapist
    received_by_name: str | None = Field(default=None, max_length=120)
    paid_at: datetime | None = None
    reference: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    recorded_by_user_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
    updated_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))


class PaymentProof(SQLModel, table=True):
    """Uploaded payment proof (receipt photo, bank transfer screenshot, etc.)."""

    __tablename__ = "payment_proof"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    payment_record_id: int = Field(foreign_key="payment_record.id", index=True)
    proof_url: str  # S3/CloudFront URL or file path
    uploaded_by_user_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))


class Receipt(SQLModel, table=True):
    """Official receipt issued to client."""

    id: int | None = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    session_id: int | None = Field(default=None, foreign_key="session.id")  # Nullable for multi-session receipts
    amount_cents: int
    currency: str = Field(default="HKD")
    description: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    payment_mode: str | None = Field(default=None, max_length=120)
    diagnosis: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    special_notes: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    pdf_url: str | None = None  # Generated receipt PDF
    status: str = Field(default="pending")  # pending|issued|voided
    issued_by_user_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))


class ClientFinancial(SQLModel, table=True):
    """Running financial totals for a client."""

    __tablename__ = "client_financial"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", unique=True, index=True)
    total_paid_cents: int = Field(default=0)  # Sum of all confirmed payments
    total_receipted_cents: int = Field(default=0)  # Sum of all issued receipts
    currency: str = Field(default="HKD")
    updated_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
