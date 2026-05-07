from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)
from app.services.invoice_documents import write_basic_invoice_pdf_file
from app.services.invoice_latex import write_latex_invoice_pdf_file
from app.services.invoice_storage import store_invoice_pdf


def _render_invoice_pdf_file(
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
) -> Path:
    renderer = settings.invoice_renderer.strip().lower()
    if renderer == "latex":
        try:
            return write_latex_invoice_pdf_file(
                invoice_id=invoice_id,
                client_id=client_id,
                client_name=client_name,
                client_address=client_address,
                client_phone=client_phone,
                amount_cents=amount_cents,
                description=description,
                diagnosis=diagnosis,
                session_start_at=session_start_at,
                therapist_name=therapist_name,
                therapist_license_number=therapist_license_number,
                payment_mode=payment_mode,
                special_notes=special_notes,
                issued_at=issued_at,
            )
        except Exception:
            logger.exception(
                "LaTeX invoice rendering failed for invoice %s", invoice_id
            )
            if not settings.invoice_latex_fallback_to_basic:
                raise
            logger.warning(
                "Falling back to basic PDF renderer for invoice %s", invoice_id
            )

    return write_basic_invoice_pdf_file(
        invoice_id=invoice_id,
        client_name=client_name,
        client_address=client_address,
        client_phone=client_phone,
        amount_cents=amount_cents,
        currency=currency,
        description=description,
        session_start_at=session_start_at,
        therapist_name=therapist_name,
        therapist_license_number=therapist_license_number,
        diagnosis=diagnosis,
        payment_mode=payment_mode,
        special_notes=special_notes,
        issued_at=issued_at,
    )


def generate_and_store_invoice_pdf_url(
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
    pdf_path = _render_invoice_pdf_file(
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
    return store_invoice_pdf(
        invoice_id=invoice_id,
        client_name=client_name,
        local_pdf_path=pdf_path,
        date_value=issued_at,
    )
