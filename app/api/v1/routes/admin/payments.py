"""Admin endpoints for recording and listing payments."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.v1.schemas.billing import (
    PaymentRecordCreateRequest,
    PaymentRecordCreateResponse,
    PaymentRecordItem,
)
from app.api.v1.schemas.client import ClientFinancialResponse
from app.core.auth import get_current_admin
from app.core.exceptions import (
    AuthorizationError,
    BusinessLogicError,
    ConflictError,
    NotFoundError,
)
from app.db.session import get_session
from app.models import Client, ClientFinancial, PaymentRecord, Session as TherapySession, User
from app.services.idempotency import (
    complete_idempotency_record,
    fail_idempotency_record,
    get_or_create_idempotency_record,
)
from app.services.timezone_utils import normalize_query_datetime, to_preferred_timezone

router = APIRouter(prefix="/admin", tags=["Admin - Payments"])


def _ensure_client_exists(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise NotFoundError("client_not_found", resource_type="client", resource_id=client_id)
    return client


def _ensure_session_for_client(
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


def _validate_payment_source(
    *,
    source: str,
    session_id: int | None,
) -> None:
    if source == "session_linked" and session_id is None:
        raise BusinessLogicError("payment_source_requires_session_id", field="session_id")
    if source == "admin_manual" and session_id is not None:
        raise BusinessLogicError("admin_manual_requires_null_session_id", field="session_id")


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
            raise ConflictError("payment_record_conflict")
    return record


def _to_financial_response(
    record: ClientFinancial,
    *,
    preferred_timezone: str | None,
) -> ClientFinancialResponse:
    available_to_receipt = max(record.total_paid_cents - record.total_receipted_cents, 0)
    return ClientFinancialResponse(
        client_id=record.client_id,
        currency=record.currency,
        total_paid_cents=record.total_paid_cents,
        total_receipted_cents=record.total_receipted_cents,
        available_to_receipt_cents=available_to_receipt,
        updated_at=to_preferred_timezone(record.updated_at, preferred_timezone),
    )


def _to_payment_item(
    payment: PaymentRecord,
    *,
    preferred_timezone: str | None,
) -> PaymentRecordItem:
    return PaymentRecordItem(
        id=payment.id,
        client_id=payment.client_id,
        source=payment.source,  # type: ignore[arg-type]
        session_id=payment.session_id,
        amount_cents=payment.amount_cents,
        currency=payment.currency,
        method=payment.payment_method,
        status=payment.status,
        received_by_role=payment.received_by_role,
        received_by_name=payment.received_by_name,
        paid_at=to_preferred_timezone(payment.paid_at, preferred_timezone) if payment.paid_at else None,
        reference=payment.reference,
        notes=payment.notes,
        recorded_by_user_id=payment.recorded_by_user_id,
        updated_at=to_preferred_timezone(payment.updated_at, preferred_timezone),
        created_at=to_preferred_timezone(payment.created_at, preferred_timezone),
    )


@router.post("/payments", response_model=PaymentRecordCreateResponse, status_code=201)
def record_payment(
    payload: PaymentRecordCreateRequest,
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
            endpoint="POST /admin/payments",
            request_body=payload.model_dump(mode="json"),
        )
        if is_existing and existing_record:
            return JSONResponse(
                status_code=existing_record.response_status,
                content=json.loads(existing_record.response_json),
            )
        try:
            result = _create_payment_record(payload, admin, db)
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

    return _create_payment_record(payload, admin, db)


def _create_payment_record(
    payload: PaymentRecordCreateRequest,
    admin: User,
    db: Session,
) -> PaymentRecordCreateResponse:
    _validate_payment_source(source=payload.source, session_id=payload.session_id)
    _ensure_client_exists(db, payload.client_id)
    if payload.session_id is not None:
        _ensure_session_for_client(
            db,
            session_id=payload.session_id,
            client_id=payload.client_id,
        )

    now = datetime.now(timezone.utc)
    paid_at = payload.paid_at or now
    currency = payload.currency.upper()
    payment = PaymentRecord(
        client_id=payload.client_id,
        source=payload.source,
        session_id=payload.session_id,
        amount_cents=payload.amount_cents,
        currency=currency,
        payment_method=payload.method,
        status="confirmed",
        received_by_role=payload.received_by_role,
        received_by_name=payload.received_by_name.strip() if payload.received_by_name else None,
        paid_at=paid_at,
        reference=payload.reference.strip() if payload.reference else None,
        notes=payload.notes.strip() if payload.notes else None,
        recorded_by_user_id=admin.id,
        created_at=now,
        updated_at=now,
    )
    db.add(payment)
    db.flush()

    financial = _get_or_create_client_financial_locked(
        db,
        client_id=payload.client_id,
        currency=currency,
    )
    financial.total_paid_cents += payload.amount_cents
    financial.currency = currency
    financial.updated_at = now
    db.add(financial)

    db.commit()
    db.refresh(payment)
    db.refresh(financial)

    return PaymentRecordCreateResponse(
        payment=_to_payment_item(payment, preferred_timezone=admin.preferred_timezone),
        financials=_to_financial_response(financial, preferred_timezone=admin.preferred_timezone),
    )


@router.get("/payments", response_model=list[PaymentRecordItem])
def list_payments(
    client_id: int | None = None,
    session_id: int | None = None,
    method: str | None = Query(default=None, pattern="^(cash|electronic)$"),
    source: str | None = Query(default=None, pattern="^(session_linked|admin_manual)$"),
    received_by_role: str | None = Query(default=None, pattern="^(admin|therapist)$"),
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    preferred_timezone = admin.preferred_timezone
    from_date = normalize_query_datetime(from_date)
    to_date = normalize_query_datetime(to_date)
    stmt = select(PaymentRecord)
    filters = []
    if client_id is not None:
        filters.append(PaymentRecord.client_id == client_id)
    if session_id is not None:
        filters.append(PaymentRecord.session_id == session_id)
    if method:
        filters.append(PaymentRecord.payment_method == method)
    if source:
        filters.append(PaymentRecord.source == source)
    if received_by_role:
        filters.append(PaymentRecord.received_by_role == received_by_role)
    if from_date:
        filters.append(func.coalesce(PaymentRecord.paid_at, PaymentRecord.created_at) >= from_date)
    if to_date:
        filters.append(func.coalesce(PaymentRecord.paid_at, PaymentRecord.created_at) <= to_date)
    if filters:
        stmt = stmt.where(and_(*filters))

    rows = db.exec(
        stmt.order_by(PaymentRecord.created_at.desc(), PaymentRecord.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [_to_payment_item(payment, preferred_timezone=preferred_timezone) for payment in rows]


@router.get("/clients/{client_id}/payments", response_model=list[PaymentRecordItem])
def list_client_payments(
    client_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
    session_id: int | None = None,
    method: str | None = Query(default=None, pattern="^(cash|electronic)$"),
    source: str | None = Query(default=None, pattern="^(session_linked|admin_manual)$"),
    received_by_role: str | None = Query(default=None, pattern="^(admin|therapist)$"),
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    _ensure_client_exists(db, client_id)
    return list_payments(
        client_id=client_id,
        session_id=session_id,
        method=method,
        source=source,
        received_by_role=received_by_role,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
        admin=admin,
        db=db,
    )
