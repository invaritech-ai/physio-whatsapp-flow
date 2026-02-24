"""Therapist invoice endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.api.v1.schemas.invoice import (
    TherapistInvoiceDetailResponse,
    TherapistInvoiceListItem,
)
from app.core.auth import get_current_therapist
from app.db.session import get_session
from app.models import Client, Receipt, Therapist
from app.services.invoice_storage import resolve_invoice_pdf_url

router = APIRouter(prefix="/therapist/invoices", tags=["Therapist Invoices"])


def _build_therapist_invoice_item(
    *,
    invoice: Receipt,
    client: Client,
) -> TherapistInvoiceListItem:
    return TherapistInvoiceListItem(
        id=invoice.id,
        client_id=invoice.client_id,
        session_id=invoice.session_id,
        therapist_id=invoice.therapist_id,
        service_type=invoice.service_type,  # type: ignore[arg-type]
        trainer_name=invoice.trainer_name,
        reference_note=invoice.reference_note,
        amount_cents=invoice.amount_cents,
        currency=invoice.currency,
        description=invoice.description,
        payment_mode=invoice.payment_mode,
        diagnosis=invoice.diagnosis,
        special_notes=invoice.special_notes,
        pdf_url=resolve_invoice_pdf_url(invoice.pdf_url),
        status=invoice.status,
        created_at=invoice.created_at,
        client_name=client.name,
        client_phone_e164=client.phone_e164,
    )


@router.get("", response_model=list[TherapistInvoiceListItem])
def list_therapist_invoices(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
    status: str | None = Query(default=None, pattern="^(pending|issued|voided)$"),
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    stmt = (
        select(Receipt, Client)
        .join(Client, Client.id == Receipt.client_id)
        .where(Receipt.therapist_id == therapist.id)
    )
    if status:
        stmt = stmt.where(Receipt.status == status)
    if from_date:
        stmt = stmt.where(Receipt.created_at >= from_date)
    if to_date:
        stmt = stmt.where(Receipt.created_at <= to_date)

    stmt = stmt.order_by(Receipt.created_at.desc(), Receipt.id.desc()).offset(offset).limit(limit)
    rows = db.exec(stmt).all()
    return [
        _build_therapist_invoice_item(invoice=invoice, client=client)
        for invoice, client in rows
    ]


@router.get("/{invoice_id}", response_model=TherapistInvoiceDetailResponse)
def get_therapist_invoice_detail(
    invoice_id: int,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
):
    row = db.exec(
        select(Receipt, Client)
        .join(Client, Client.id == Receipt.client_id)
        .where(
            Receipt.therapist_id == therapist.id,
            Receipt.id == invoice_id,
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="invoice_not_found")

    invoice, client = row
    item = _build_therapist_invoice_item(invoice=invoice, client=client)
    return TherapistInvoiceDetailResponse(
        **item.model_dump(),
        issued_by_user_id=invoice.issued_by_user_id,
    )


@router.get("/{invoice_id}/pdf")
def download_therapist_invoice_pdf(
    invoice_id: int,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
):
    """Redirect to a fresh pre-signed PDF download URL. Safe to link directly — never expires."""
    row = db.exec(
        select(Receipt)
        .where(Receipt.therapist_id == therapist.id, Receipt.id == invoice_id)
    ).first()
    if not row or not row.pdf_url:
        raise HTTPException(status_code=404, detail="invoice_not_found")
    url = resolve_invoice_pdf_url(row.pdf_url)
    if not url:
        raise HTTPException(status_code=404, detail="invoice_not_found")
    return RedirectResponse(url=url, status_code=307)
