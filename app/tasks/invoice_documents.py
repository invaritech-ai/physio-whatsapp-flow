"""Celery tasks for invoice document generation."""

from __future__ import annotations

from datetime import datetime

from app.services.invoice_generation import generate_and_store_invoice_pdf_url
from app.worker import celery_app


@celery_app.task(
    name="tasks.generate_invoice_pdf",
    bind=True,
    autoretry_for=(OSError, RuntimeError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def generate_invoice_pdf(
    self,
    *,
    invoice_id: int,
    client_id: int,
    client_name: str | None,
    client_address: str | None,
    client_phone: str,
    amount_cents: int,
    currency: str,
    description: str,
    diagnosis: str | None,
    session_start_at: datetime | None,
    therapist_name: str | None,
    therapist_license_number: str | None,
    payment_mode: str | None,
    special_notes: str | None,
    issued_at: datetime | None,
) -> str:
    """Generate and store invoice PDF, returning a public URL."""
    return generate_and_store_invoice_pdf_url(
        invoice_id=invoice_id,
        client_id=client_id,
        client_name=client_name,
        client_address=client_address,
        client_phone=client_phone,
        amount_cents=amount_cents,
        currency=currency,
        description=description,
        diagnosis=diagnosis,
        session_start_at=session_start_at,
        therapist_name=therapist_name,
        therapist_license_number=therapist_license_number,
        payment_mode=payment_mode,
        special_notes=special_notes,
        issued_at=issued_at,
    )
