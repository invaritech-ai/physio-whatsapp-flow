"""Admin endpoints for invoice management."""

import json
import re
import logging
from datetime import datetime, timezone
from typing import cast

from celery import Task
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.v1.schemas.invoice import (
    InvoiceDetailResponse,
    InvoiceGenerateRequest,
    InvoiceListItem,
)
from app.core.auth import get_current_admin
from app.core.config import settings
from app.core.exceptions import (
    AppException,
    AuthorizationError,
    BusinessLogicError,
    ConflictError,
    NotFoundError,
)
from app.db.session import get_session
from app.models import (
    Client,
    ClientFinancial,
    InvoicePreset,
    PaymentRecord,
    Receipt,
    Session as TherapySession,
    SessionNote,
    Therapist,
    User,
)
from app.services.idempotency import (
    complete_idempotency_record,
    fail_idempotency_record,
    get_or_create_idempotency_record,
)
from app.services.invoice_generation import generate_and_store_invoice_pdf_url
from app.services.invoice_storage import resolve_invoice_pdf_url
from app.services.pricing import load_active_plan_map, resolve_expected_charge
from app.services.timezone_utils import normalize_query_datetime, to_preferred_timezone

router = APIRouter(prefix="/admin/invoices", tags=["Admin - Invoices"])
logger = logging.getLogger(__name__)
_DIAGNOSIS_PATTERN = re.compile(r"diagnosis\s*:\s*(.+)", re.IGNORECASE)
_SERVICE_TYPE_VALUES = {"standard", "supervised_physio", "other"}


def _ensure_client_exists(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise NotFoundError("client_not_found", resource_type="client", resource_id=client_id)
    return client


def _ensure_session_belongs_to_client(
    db: Session,
    *,
    session_id: int,
    client_id: int,
) -> TherapySession:
    session_row = db.get(TherapySession, session_id)
    if not session_row:
        raise NotFoundError("session_not_found", resource_type="session", resource_id=session_id)
    if session_row.client_id != client_id:
        raise BusinessLogicError("invalid_session_for_client", details={"session_id": session_id, "client_id": client_id})
    return session_row


def _ensure_therapist_exists(db: Session, therapist_id: int) -> Therapist:
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise NotFoundError("therapist_not_found", resource_type="therapist", resource_id=therapist_id)
    return therapist


def _ensure_invoice_exists(db: Session, invoice_id: int) -> Receipt:
    invoice = db.get(Receipt, invoice_id)
    if not invoice:
        raise NotFoundError("invoice_not_found", resource_type="invoice", resource_id=invoice_id)
    return invoice


def _get_or_create_client_financial_locked(
    db: Session,
    *,
    client_id: int,
    currency: str,
) -> ClientFinancial:
    stmt = select(ClientFinancial).where(ClientFinancial.client_id == client_id)
    bind = db.get_bind()
    if bind is not None and bind.dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    record = db.exec(stmt).first()
    if record:
        return record

    record = ClientFinancial(
        client_id=client_id,
        currency=currency,
        total_paid_cents=0,
        total_receipted_cents=0,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        record = db.exec(
            select(ClientFinancial).where(ClientFinancial.client_id == client_id)
        ).first()
        if not record:
            raise ConflictError("invoice_generation_conflict")
    return record


def _to_invoice_list_item(
    invoice: Receipt,
    *,
    preferred_timezone: str | None,
) -> InvoiceListItem:
    return InvoiceListItem(
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
        created_at=to_preferred_timezone(invoice.created_at, preferred_timezone),
    )


def _to_invoice_detail(
    invoice: Receipt,
    *,
    preferred_timezone: str | None,
) -> InvoiceDetailResponse:
    list_item = _to_invoice_list_item(invoice, preferred_timezone=preferred_timezone)
    return InvoiceDetailResponse(
        **list_item.model_dump(),
        issued_by_user_id=invoice.issued_by_user_id,
    )


def _resolve_invoice_preset_value(
    *,
    db: Session,
    preset_id: int | None,
    preset_type: str,
    invalid_detail: str,
) -> str | None:
    if preset_id is None:
        return None
    preset = db.get(InvoicePreset, preset_id)
    if not preset:
        raise BusinessLogicError(invalid_detail, details={"preset_id": preset_id})
    if preset.preset_type != preset_type or not preset.is_active:
        raise BusinessLogicError(invalid_detail, details={"preset_id": preset_id, "preset_type": preset_type, "is_active": False})
    return preset.value


def _generate_invoice_pdf_url(
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
    kwargs = {
        "invoice_id": invoice_id,
        "client_id": client_id,
        "client_name": client_name,
        "client_address": client_address,
        "client_phone": client_phone,
        "amount_cents": amount_cents,
        "currency": currency,
        "description": description,
        "diagnosis": diagnosis,
        "session_start_at": session_start_at,
        "therapist_name": therapist_name,
        "therapist_license_number": therapist_license_number,
        "payment_mode": payment_mode,
        "special_notes": special_notes,
        "issued_at": issued_at,
    }
    if not settings.celery_invoice_pdf_task_enabled:
        return generate_and_store_invoice_pdf_url(**kwargs)

    from app.tasks.invoice_documents import generate_invoice_pdf

    try:
        task = cast(Task, generate_invoice_pdf).delay(**kwargs)
        result = task.get(timeout=settings.celery_invoice_task_timeout_seconds)
        if isinstance(result, str) and result.strip():
            return result
        raise RuntimeError("invoice_pdf_url_empty")
    except Exception:
        logger.exception(
            "celery invoice generation failed invoice_id=%s; falling back to inline",
            invoice_id,
        )
        return generate_and_store_invoice_pdf_url(**kwargs)


@router.get("", response_model=list[InvoiceListItem])
def list_invoices(
    client_id: int | None = None,
    therapist_id: int | None = None,
    status: str | None = Query(default=None, pattern="^(pending|issued|voided)$"),
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    preferred_timezone = admin.preferred_timezone
    from_date = normalize_query_datetime(from_date)
    to_date = normalize_query_datetime(to_date)

    stmt = select(Receipt)
    if therapist_id is not None:
        stmt = stmt.where(Receipt.therapist_id == therapist_id)
    if client_id is not None:
        stmt = stmt.where(Receipt.client_id == client_id)
    if status:
        stmt = stmt.where(Receipt.status == status)
    if from_date:
        stmt = stmt.where(Receipt.created_at >= from_date)
    if to_date:
        stmt = stmt.where(Receipt.created_at <= to_date)

    stmt = stmt.order_by(Receipt.created_at.desc(), Receipt.id.desc()).offset(offset).limit(limit)
    invoices = db.exec(stmt).all()
    return [_to_invoice_list_item(invoice, preferred_timezone=preferred_timezone) for invoice in invoices]


@router.get("/{invoice_id}", response_model=InvoiceDetailResponse)
def get_invoice_detail(
    invoice_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    preferred_timezone = admin.preferred_timezone
    invoice = _ensure_invoice_exists(db, invoice_id)
    return _to_invoice_detail(invoice, preferred_timezone=preferred_timezone)


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Redirect to a fresh pre-signed PDF download URL. Safe to link directly — never expires."""
    invoice = _ensure_invoice_exists(db, invoice_id)
    if not invoice.pdf_url:
        raise NotFoundError("invoice_not_found", resource_type="invoice_pdf", resource_id=invoice_id)
    url = resolve_invoice_pdf_url(invoice.pdf_url)
    if not url:
        raise NotFoundError("invoice_not_found", resource_type="invoice_pdf", resource_id=invoice_id)
    return RedirectResponse(url=url, status_code=307)


@router.post("/generate", response_model=InvoiceDetailResponse, status_code=201)
def generate_invoice(
    payload: InvoiceGenerateRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if admin.id is None:
        raise AuthorizationError("access_denied")

    if idempotency_key:
        existing_record, is_existing = get_or_create_idempotency_record(
            db,
            idempotency_key=idempotency_key,
            endpoint="POST /admin/invoices/generate",
            request_body=payload.model_dump(mode="json"),
        )
        if is_existing and existing_record:
            return JSONResponse(
                status_code=existing_record.response_status,
                content=json.loads(existing_record.response_json),
            )
        try:
            result = _generate_invoice_impl(payload, admin, db)
            if idempotency_key:
                complete_idempotency_record(
                    db,
                    idempotency_key=idempotency_key,
                    response_status=201,
                    response_json=result.model_dump_json(),
                )
            return result
        except Exception as exc:
            if idempotency_key:
                fail_idempotency_record(db, idempotency_key=idempotency_key)
            raise

    return _generate_invoice_impl(payload, admin, db)


def _generate_invoice_impl(
    payload: InvoiceGenerateRequest,
    admin: User,
    db: Session,
) -> InvoiceDetailResponse:

    def _clean_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    client = _ensure_client_exists(db, payload.client_id)
    session_row: TherapySession | None = None
    if payload.session_id is not None:
        session_row = _ensure_session_belongs_to_client(
            db,
            session_id=payload.session_id,
            client_id=payload.client_id,
        )

    service_type = payload.service_type.strip().lower()
    if service_type not in _SERVICE_TYPE_VALUES:
        raise BusinessLogicError("invalid_service_type", field="service_type")

    default_amount_cents: int | None = None
    if session_row is not None:
        plan_map = load_active_plan_map(db, client_ids={payload.client_id})
        default_amount_cents, _, _ = resolve_expected_charge(session_row, plan_map=plan_map)

    amount_cents = payload.amount_cents if payload.amount_cents is not None else default_amount_cents
    if amount_cents is None or amount_cents <= 0:
        raise BusinessLogicError("amount_cents_required", field="amount_cents")

    if (
        session_row is not None
        and payload.therapist_id is not None
        and payload.therapist_id != session_row.therapist_id
    ):
        raise BusinessLogicError("therapist_session_mismatch", details={"therapist_id": payload.therapist_id, "session_therapist_id": session_row.therapist_id})

    therapist_id = payload.therapist_id
    if therapist_id is None and session_row is not None:
        therapist_id = session_row.therapist_id

    therapist = _ensure_therapist_exists(db, therapist_id) if therapist_id is not None else None
    therapist_name = therapist.display_name if therapist else None
    therapist_license_number = therapist.license_number if therapist else None

    payment_record = None
    latest_note = None
    if session_row is not None and session_row.id is not None:
        payment_record = db.exec(
            select(PaymentRecord)
            .where(PaymentRecord.session_id == session_row.id)
            .order_by(PaymentRecord.created_at.desc())
        ).first()
        latest_note = db.exec(
            select(SessionNote)
            .where(SessionNote.session_id == session_row.id)
            .order_by(SessionNote.created_at.desc())
        ).first()

    payment_mode = _clean_optional_text(payload.payment_mode)
    if payment_mode is None and payment_record and payment_record.payment_method:
        payment_mode = payment_record.payment_method.replace("_", " ").title()
    if payment_mode is None:
        payment_mode = "N/A"

    extracted_diagnosis = None
    if latest_note and latest_note.note_text:
        match = _DIAGNOSIS_PATTERN.search(latest_note.note_text)
        if match:
            extracted_diagnosis = match.group(1).strip()
    diagnosis_preset_value = _resolve_invoice_preset_value(
        db=db,
        preset_id=payload.diagnosis_preset_id,
        preset_type="diagnosis",
        invalid_detail="invalid_diagnosis_preset_id",
    )
    special_note_preset_value = _resolve_invoice_preset_value(
        db=db,
        preset_id=payload.special_note_preset_id,
        preset_type="special_note",
        invalid_detail="invalid_special_note_preset_id",
    )
    diagnosis = _clean_optional_text(payload.diagnosis) or diagnosis_preset_value or extracted_diagnosis or "-"
    special_notes = _clean_optional_text(payload.special_notes) or special_note_preset_value or "-"
    trainer_name = _clean_optional_text(payload.trainer_name)
    reference_note = _clean_optional_text(payload.reference_note)
    description = payload.description.strip()

    currency = payload.currency.upper()
    financial = _get_or_create_client_financial_locked(
        db,
        client_id=payload.client_id,
        currency=currency,
    )
    available_to_receipt_cents = max(
        financial.total_paid_cents - financial.total_receipted_cents,
        0,
    )
    if amount_cents > available_to_receipt_cents:
        raise BusinessLogicError("amount_exceeds_available_to_receipt", details={"amount_cents": amount_cents, "available_to_receipt_cents": available_to_receipt_cents})

    now = datetime.now(timezone.utc)
    invoice = Receipt(
        client_id=payload.client_id,
        session_id=session_row.id if session_row else None,
        therapist_id=therapist_id,
        service_type=service_type,
        trainer_name=trainer_name,
        reference_note=reference_note,
        amount_cents=amount_cents,
        currency=currency,
        description=description,
        payment_mode=payment_mode,
        diagnosis=diagnosis,
        special_notes=special_notes,
        status="pending",
        issued_by_user_id=admin.id,
        created_at=now,
    )
    db.add(invoice)
    db.flush()

    try:
        invoice.pdf_url = _generate_invoice_pdf_url(
            invoice_id=invoice.id,
            client_id=client.id,
            client_name=client.name,
            client_address=client.address,
            client_phone=client.phone_e164,
            amount_cents=amount_cents,
            currency=currency,
            description=description,
            diagnosis=diagnosis,
            session_start_at=session_row.start_time if session_row else now,
            therapist_name=therapist_name,
            therapist_license_number=therapist_license_number,
            payment_mode=payment_mode,
            special_notes=special_notes,
            issued_at=now,
        )
    except (OSError, RuntimeError) as exc:
        db.rollback()
        error_code = "invoice_pdf_generation_failed"
        if "s3" in str(exc).lower() or "upload" in str(exc).lower():
            error_code = "invoice_upload_failed"
        raise AppException(error_code, status_code=500) from exc

    invoice.status = "issued"
    financial.total_receipted_cents += amount_cents
    financial.currency = currency
    financial.updated_at = now
    db.add(financial)
    db.add(invoice)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("invoice_generation_conflict") from exc

    db.refresh(invoice)
    return _to_invoice_detail(invoice, preferred_timezone=admin.preferred_timezone)
