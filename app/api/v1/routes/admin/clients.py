"""Admin endpoints for client (patient) management."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.api.v1.schemas.client import (
    ClientCreate,
    ClientDetailResponse,
    ClientFinancialResponse,
    ClientFinancialSummary,
    ClientListItem,
    ClientListResponse,
    ClientMessageListItem,
    ClientMessageListResponse,
    ClientSessionListItem,
    ClientUpdate,
)
from app.api.v1.schemas.invoice import (
    ReceiptingSummaryReceiptItem,
    ReceiptingSummaryResponse,
)
from app.core.auth import get_current_admin
from app.core.config import settings
from app.core.exceptions import BusinessLogicError, NotFoundError
from app.db.session import get_session
from app.models import Client, ClientFinancial, MessageLog, PaymentRecord, Receipt, Session as TherapySession, Therapist, User
from app.models.billing import ClientPlanAssignment
from app.services.clinical_note_visibility import (
    clinical_note_preview,
    latest_session_note_by_session_id,
)
from app.services.pricing import (
    load_active_plan_map,
    resolve_expected_charge,
)
from app.services.timezone_utils import normalize_query_datetime, to_preferred_timezone

router = APIRouter(prefix="/admin/clients", tags=["Admin - Clients"])


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _ensure_client_exists(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise NotFoundError("client_not_found", resource_type="client", resource_id=client_id)
    return client


def _ensure_preferred_therapist_exists(db: Session, therapist_id: int | None) -> None:
    if therapist_id is None:
        return
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise BusinessLogicError("therapist_not_found", field="preferred_therapist_id", details={"therapist_id": therapist_id})


def _ensure_unique_phone(
    db: Session,
    phone_e164: str,
    *,
    ignore_client_id: int | None = None,
) -> None:
    existing = db.exec(select(Client).where(Client.phone_e164 == phone_e164)).first()
    if existing and existing.id != ignore_client_id:
        raise BusinessLogicError("client_phone_already_exists", field="phone_e164", details={"phone_e164": phone_e164})


def _to_receipting_summary_item(receipt: Receipt) -> ReceiptingSummaryReceiptItem:
    return ReceiptingSummaryReceiptItem(
        id=receipt.id,
        session_id=receipt.session_id,
        service_type=receipt.service_type,  # type: ignore[arg-type]
        amount_cents=receipt.amount_cents,
        currency=receipt.currency,
        description=receipt.description,
        created_at=receipt.created_at,
    )


def _load_confirmed_payment_totals_by_session(
    db: Session,
    *,
    client_id: int,
    session_ids: set[int],
) -> dict[int, tuple[int, str]]:
    if not session_ids:
        return {}

    rows = db.exec(
        select(
            PaymentRecord.session_id,
            func.coalesce(func.sum(PaymentRecord.amount_cents), 0),
            func.max(PaymentRecord.currency),
        )
        .where(
            PaymentRecord.client_id == client_id,
            PaymentRecord.status == "confirmed",
            PaymentRecord.session_id.in_(session_ids),  # type: ignore[arg-type]
        )
        .group_by(PaymentRecord.session_id)
    ).all()

    result: dict[int, tuple[int, str]] = {}
    for session_id, total_amount_cents, currency in rows:
        if session_id is None:
            continue
        amount_cents = int(total_amount_cents or 0)
        if amount_cents <= 0:
            continue
        result[session_id] = (amount_cents, currency or settings.default_currency)
    return result


@router.get("", response_model=ClientListResponse)
def list_clients(
    q: str | None = None,
    phone_e164: str | None = None,
    email: str | None = None,
    date_of_birth: date | None = None,
    preferred_therapist_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """List/search clients for admin workspace."""
    _ = admin
    filters = []

    if phone_e164:
        filters.append(Client.phone_e164 == phone_e164)
    if email:
        like_email = f"%{email.strip()}%"
        filters.append(Client.email.ilike(like_email))  # type: ignore[arg-type]
    if date_of_birth:
        filters.append(Client.date_of_birth == date_of_birth)
    if preferred_therapist_id is not None:
        filters.append(Client.preferred_therapist_id == preferred_therapist_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                Client.name.ilike(like),  # type: ignore[arg-type]
                Client.phone_e164.ilike(like),  # type: ignore[arg-type]
                Client.email.ilike(like),  # type: ignore[arg-type]
            )
        )

    total_stmt = select(func.count()).select_from(Client)
    items_stmt = (
        select(Client, ClientFinancial)
        .outerjoin(ClientFinancial, ClientFinancial.client_id == Client.id)
    )
    for condition in filters:
        total_stmt = total_stmt.where(condition)
        items_stmt = items_stmt.where(condition)

    total = db.exec(total_stmt).one()
    rows = db.exec(
        items_stmt.order_by(Client.created_at.desc()).offset(offset).limit(limit)
    ).all()

    client_ids = [client.id for client, _ in rows if client.id is not None]
    plan_flags: dict[int, set[int]] = {}
    if client_ids:
        plan_rows = db.exec(
            select(ClientPlanAssignment.client_id, ClientPlanAssignment.duration_minutes)
            .where(
                ClientPlanAssignment.client_id.in_(client_ids),
                ClientPlanAssignment.is_active == True,
            )
        ).all()
        for cid, duration in plan_rows:
            plan_flags.setdefault(cid, set()).add(duration)

    items = []
    for client, financial in rows:
        summary = ClientFinancialSummary(
            total_paid_cents=None if financial is None else financial.total_paid_cents,
            total_receipted_cents=None if financial is None else financial.total_receipted_cents,
            available_to_receipt_cents=(
                None
                if financial is None
                else max(financial.total_paid_cents - financial.total_receipted_cents, 0)
            ),
            currency=None if financial is None else financial.currency,
        )
        durations = plan_flags.get(client.id, set())
        items.append(
            ClientListItem.model_validate(client).model_copy(
                update={
                    "financials_summary": summary,
                    "has_30min_plan": 30 in durations,
                    "has_45min_plan": 45 in durations,
                }
            )
        )

    return ClientListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(items)) < total,
    )


@router.post("", response_model=ClientDetailResponse, status_code=201)
def create_client(
    data: ClientCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Create a new client."""
    _ = admin
    _ensure_unique_phone(db, data.phone_e164)
    _ensure_preferred_therapist_exists(db, data.preferred_therapist_id)

    client = Client(
        phone_e164=data.phone_e164,
        name=data.name,
        preferred_name=data.preferred_name,
        email=str(data.email) if data.email else None,
        date_of_birth=data.date_of_birth,
        address=data.address,
        diagnosis=_clean_optional_text(data.diagnosis),
        preferred_therapist_id=data.preferred_therapist_id,
        default_receipt_amount_cents=data.default_receipt_amount_cents,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientDetailResponse)
def get_client(
    client_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Get a single client."""
    _ = admin
    return _ensure_client_exists(db, client_id)


@router.patch("/{client_id}", response_model=ClientDetailResponse)
def update_client(
    client_id: int,
    data: ClientUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Update an existing client."""
    _ = admin
    client = _ensure_client_exists(db, client_id)

    if "phone_e164" in data.model_fields_set and data.phone_e164 is not None:
        _ensure_unique_phone(db, data.phone_e164, ignore_client_id=client.id)
        client.phone_e164 = data.phone_e164
    if "name" in data.model_fields_set:
        client.name = data.name
    if "preferred_name" in data.model_fields_set:
        client.preferred_name = data.preferred_name
    if "email" in data.model_fields_set:
        client.email = str(data.email) if data.email else None
    if "date_of_birth" in data.model_fields_set:
        client.date_of_birth = data.date_of_birth
    if "address" in data.model_fields_set:
        client.address = data.address
    if "diagnosis" in data.model_fields_set:
        client.diagnosis = _clean_optional_text(data.diagnosis)
    if "preferred_therapist_id" in data.model_fields_set:
        _ensure_preferred_therapist_exists(db, data.preferred_therapist_id)
        client.preferred_therapist_id = data.preferred_therapist_id
    if "default_receipt_amount_cents" in data.model_fields_set:
        client.default_receipt_amount_cents = data.default_receipt_amount_cents

    client.updated_at = datetime.now(timezone.utc)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.get("/{client_id}/sessions", response_model=list[ClientSessionListItem])
def list_client_sessions(
    client_id: int,
    status: str | None = None,
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """List sessions for a client."""
    preferred_timezone = admin.preferred_timezone
    from_date = normalize_query_datetime(from_date)
    to_date = normalize_query_datetime(to_date)
    _ensure_client_exists(db, client_id)

    stmt = select(TherapySession).where(TherapySession.client_id == client_id)
    if status:
        stmt = stmt.where(TherapySession.status == status)
    if from_date:
        stmt = stmt.where(TherapySession.start_time >= from_date)
    if to_date:
        stmt = stmt.where(TherapySession.start_time <= to_date)

    stmt = stmt.order_by(TherapySession.start_time.desc()).offset(offset).limit(limit)
    sessions = db.exec(stmt).all()
    plan_map = load_active_plan_map(db, client_ids={client_id})
    session_ids = [session.id for session in sessions if session.id is not None]
    payment_totals_by_session = _load_confirmed_payment_totals_by_session(
        db,
        client_id=client_id,
        session_ids=set(session_ids),
    )
    # Latest clinical note per session (any author) so the timeline can flag
    # which sessions have notes, matching the admin clinical-note read path.
    note_map = latest_session_note_by_session_id(
        db,
        therapist_user_id=None,
        session_ids=session_ids,
    )
    rows: list[ClientSessionListItem] = []
    for session in sessions:
        expected_charge_cents, expected_charge_currency, assigned_plan = resolve_expected_charge(
            session,
            plan_map=plan_map,
        )
        charge_amount_cents = session.charge_amount_cents
        currency = session.currency
        if charge_amount_cents is None and session.id is not None:
            payment_total = payment_totals_by_session.get(session.id)
            if payment_total is not None:
                charge_amount_cents, currency = payment_total
        note = note_map.get(session.id) if session.id is not None else None
        rows.append(
            ClientSessionListItem(
                id=session.id,
                therapist_id=session.therapist_id,
                start_time=to_preferred_timezone(session.start_time, preferred_timezone),
                end_time=to_preferred_timezone(session.end_time, preferred_timezone),
                duration_minutes=session.duration_minutes,
                status=session.status,
                source=session.source,
                charge_amount_cents=charge_amount_cents,
                currency=currency,
                expected_charge_cents=expected_charge_cents,
                expected_charge_currency=expected_charge_currency,
                assigned_plan=assigned_plan,
                has_clinical_note=note is not None,
                clinical_note_preview=clinical_note_preview(note.note_text) if note else None,
            )
        )
    return rows


@router.get("/{client_id}/messages", response_model=ClientMessageListResponse)
def list_client_messages(
    client_id: int,
    direction: str | None = Query(None, pattern="^(inbound|outbound)$"),
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = Query(default=None, gt=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """List message history for a client with cursor pagination."""
    _ = admin
    _ensure_client_exists(db, client_id)

    stmt = select(MessageLog).where(MessageLog.client_id == client_id)
    if direction:
        stmt = stmt.where(MessageLog.direction == direction)
    if before_id is not None:
        stmt = stmt.where(MessageLog.id < before_id)

    page_size = limit + 1
    rows = db.exec(
        stmt.order_by(MessageLog.created_at.desc(), MessageLog.id.desc()).limit(page_size)
    ).all()
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    rows.reverse()
    return ClientMessageListResponse(
        items=[ClientMessageListItem.model_validate(row) for row in rows],
        has_more=has_more,
    )


@router.get("/{client_id}/financials", response_model=ClientFinancialResponse)
def get_client_financials(
    client_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Return current financial totals for a client."""
    preferred_timezone = admin.preferred_timezone
    client = _ensure_client_exists(db, client_id)
    record = db.exec(
        select(ClientFinancial).where(ClientFinancial.client_id == client_id)
    ).first()

    if not record:
        return ClientFinancialResponse(
            client_id=client_id,
            currency=settings.default_currency,
            total_paid_cents=0,
            total_receipted_cents=0,
            available_to_receipt_cents=0,
            updated_at=to_preferred_timezone(client.updated_at, preferred_timezone),
        )

    available = max(record.total_paid_cents - record.total_receipted_cents, 0)
    return ClientFinancialResponse(
        client_id=client_id,
        currency=record.currency,
        total_paid_cents=record.total_paid_cents,
        total_receipted_cents=record.total_receipted_cents,
        available_to_receipt_cents=available,
        updated_at=to_preferred_timezone(record.updated_at, preferred_timezone),
    )


@router.get("/{client_id}/receipting/summary", response_model=ReceiptingSummaryResponse)
def get_client_receipting_summary(
    client_id: int,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Return running receipting totals plus paginated receipt ledger for a client."""
    _ = admin
    _ensure_client_exists(db, client_id)

    financial = db.exec(
        select(ClientFinancial).where(ClientFinancial.client_id == client_id)
    ).first()
    currency = financial.currency if financial else settings.default_currency
    total_paid_cents = financial.total_paid_cents if financial else 0
    total_receipted_cents = financial.total_receipted_cents if financial else 0
    claimable_balance_cents = max(total_paid_cents - total_receipted_cents, 0)

    total_receipts = db.exec(
        select(func.count()).select_from(Receipt).where(Receipt.client_id == client_id)
    ).one()
    receipts = db.exec(
        select(Receipt)
        .where(Receipt.client_id == client_id)
        .order_by(Receipt.created_at.desc(), Receipt.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return ReceiptingSummaryResponse(
        client_id=client_id,
        currency=currency,
        total_paid_cents=total_paid_cents,
        total_receipted_cents=total_receipted_cents,
        claimable_balance_cents=claimable_balance_cents,
        receipts=[_to_receipting_summary_item(receipt) for receipt in receipts],
        limit=limit,
        offset=offset,
        has_more=(offset + len(receipts)) < total_receipts,
    )
