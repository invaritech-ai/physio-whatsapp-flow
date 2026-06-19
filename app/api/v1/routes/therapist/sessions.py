"""Therapist session endpoints — calendar view and session detail."""

from datetime import datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.auth import get_current_therapist
from app.db.session import get_session
from app.models import Client, PaymentRecord, SessionNote, Therapist
from app.models import Session as TherapySession
from app.api.v1.schemas.clinical_note import (
    ClinicalNoteResponse,
    ClinicalNoteUpsertRequest,
)
from app.api.v1.schemas.session import (
    SessionDetail,
    SessionListItem,
    SessionListResponse,
    SessionStatusUpdateRequest,
    SessionStatusUpdateResponse,
    SessionSummary,
    TherapistRecordPaymentRequest,
    TherapistRecordPaymentResponse,
)
from app.services.clinical_note_visibility import (
    clinical_note_preview,
    latest_session_note_by_session_id,
)
from app.services.pricing import (
    load_active_plan_map,
    load_therapist_slot_price_map,
    resolve_expected_charge,
)
from app.services.timezone_utils import (
    as_utc,
    normalize_query_datetime,
    to_preferred_timezone,
)

router = APIRouter(prefix="/sessions", tags=["Therapist Sessions"])
_DIAGNOSIS_PATTERN = re.compile(r"diagnosis\s*:\s*(.+)", re.IGNORECASE)


def _parse_datetime_query(value: str | None) -> datetime | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None

    # Tolerate raw `+00:00` offsets in query strings where `+` may arrive as space.
    normalized = raw.replace(" ", "+")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid_datetime",
        )


def _build_list_item(
    session: TherapySession,
    client: Client,
    *,
    preferred_timezone: str | None,
    plan_map: dict[tuple[int, int], dict[str, object]],
    clinical_note: SessionNote | None = None,
    slot_price_map: dict[tuple[int, int], dict[str, object]] | None = None,
) -> SessionListItem:
    expected_charge_cents, expected_charge_currency, assigned_plan = (
        resolve_expected_charge(
            session,
            plan_map=plan_map,
            slot_price_map=slot_price_map,
        )
    )
    preview = clinical_note_preview(clinical_note.note_text) if clinical_note else None
    return SessionListItem(
        id=session.id or 0,
        client_id=session.client_id,
        client_name=client.name,
        client_phone=client.phone_e164,
        start_time=to_preferred_timezone(session.start_time, preferred_timezone),
        end_time=to_preferred_timezone(session.end_time, preferred_timezone),
        duration_minutes=session.duration_minutes,
        status=session.status,
        expected_charge_cents=expected_charge_cents,
        expected_charge_currency=expected_charge_currency,
        assigned_plan=assigned_plan,
        has_clinical_note=clinical_note is not None,
        clinical_note_preview=preview,
    )


def _extract_diagnosis(note_text: str) -> str | None:
    match = _DIAGNOSIS_PATTERN.search(note_text)
    if not match:
        return None
    return match.group(1).strip() or None


def _normalize_note_text(note_text: str) -> str:
    normalized = note_text.replace("\r\n", "\n").replace("\r", "\n")
    # Backward compatibility for previously persisted escaped newlines.
    if "\\n" in normalized:
        normalized = normalized.replace("\\n", "\n")
    return normalized


def _merge_note_with_diagnosis(
    note_text: str, diagnosis: str | None
) -> tuple[str, str | None]:
    clean_note = _normalize_note_text(note_text.strip())
    if diagnosis is None:
        derived = _extract_diagnosis(clean_note)
        return clean_note, derived

    clean_diagnosis = diagnosis.strip()
    if not clean_diagnosis:
        derived = _extract_diagnosis(clean_note)
        return clean_note, derived

    if _DIAGNOSIS_PATTERN.search(clean_note):
        merged = _DIAGNOSIS_PATTERN.sub(
            f"Diagnosis: {clean_diagnosis}", clean_note, count=1
        )
    else:
        merged = f"{clean_note}\n\nDiagnosis: {clean_diagnosis}"
    return merged, clean_diagnosis


def _build_clinical_note_response(
    note: SessionNote,
    *,
    diagnosis: str | None,
    updated_at: datetime | None = None,
) -> ClinicalNoteResponse:
    effective_updated_at = updated_at or note.created_at
    return ClinicalNoteResponse(
        session_id=note.session_id,
        note_id=note.id or 0,
        note_text=_normalize_note_text(note.note_text),
        diagnosis=diagnosis,
        author_user_id=note.author_user_id,
        created_at=note.created_at,
        updated_at=effective_updated_at,
    )


def _get_therapist_session_or_404(
    db: Session,
    *,
    therapist_id: int,
    session_id: int,
) -> TherapySession:
    session_row = db.exec(
        select(TherapySession).where(
            TherapySession.id == session_id,
            TherapySession.therapist_id == therapist_id,
        )
    ).first()
    if not session_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return session_row


@router.get("", response_model=SessionListResponse)
def list_sessions(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
    scope: str | None = Query(None, pattern="^(upcoming|past|all)$"),
    from_date_raw: str | None = Query(None, alias="from"),
    to_date_raw: str | None = Query(None, alias="to"),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List current therapist's sessions, with optional date range and scope filter."""
    now = datetime.now(timezone.utc)
    from_date = normalize_query_datetime(_parse_datetime_query(from_date_raw))
    to_date = normalize_query_datetime(_parse_datetime_query(to_date_raw))

    filters = [TherapySession.therapist_id == therapist.id]

    # Apply scope filter
    if scope == "upcoming":
        filters.append(TherapySession.start_time >= now)
    elif scope == "past":
        filters.append(TherapySession.start_time < now)

    # Apply date range filters
    if from_date:
        filters.append(TherapySession.start_time >= from_date)
    if to_date:
        filters.append(TherapySession.start_time <= to_date)

    total_stmt = select(func.count()).select_from(TherapySession)
    items_stmt = select(TherapySession)
    for condition in filters:
        total_stmt = total_stmt.where(condition)
        items_stmt = items_stmt.where(condition)

    total = int(db.exec(total_stmt).one())
    # sessions = db.exec(
    #     items_stmt.order_by(TherapySession.start_time).offset(offset).limit(limit)
    # ).all()
    if scope == "past":
        ordered_items_stmt = items_stmt.order_by(TherapySession.start_time.desc())
    else:
        ordered_items_stmt = items_stmt.order_by(TherapySession.start_time.asc())

    paginated_items_stmt = ordered_items_stmt.offset(offset).limit(limit)

    sessions = db.exec(paginated_items_stmt).all()

    # Batch-load clients
    client_ids = {s.client_id for s in sessions}
    clients = {}
    if client_ids:
        client_rows = db.exec(
            select(Client).where(Client.id.in_(client_ids))  # type: ignore
        ).all()
        clients = {c.id: c for c in client_rows}

    plan_map = load_active_plan_map(db, client_ids=client_ids)
    slot_price_map = load_therapist_slot_price_map(db, therapist_ids={therapist.id})
    session_ids = [s.id for s in sessions if s.id is not None]
    note_map = latest_session_note_by_session_id(
        db,
        therapist_user_id=therapist.user_id,
        session_ids=session_ids,
    )
    items = [
        _build_list_item(
            s,
            clients.get(s.client_id, Client(phone_e164="")),
            preferred_timezone=therapist.preferred_timezone,
            plan_map=plan_map,
            clinical_note=note_map.get(s.id) if s.id is not None else None,
            slot_price_map=slot_price_map,
        )
        for s in sessions
    ]
    return SessionListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(items)) < total,
    )


@router.get("/summary", response_model=SessionSummary)
def session_summary(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
    from_date_raw: str | None = Query(None, alias="from"),
    to_date_raw: str | None = Query(None, alias="to"),
):
    """Get session counts and next upcoming session."""
    now = datetime.now(timezone.utc)
    from_date = normalize_query_datetime(_parse_datetime_query(from_date_raw))
    to_date = normalize_query_datetime(_parse_datetime_query(to_date_raw))

    # Base query for this therapist
    base = select(TherapySession).where(TherapySession.therapist_id == therapist.id)
    if from_date:
        base = base.where(TherapySession.start_time >= from_date)
    if to_date:
        base = base.where(TherapySession.start_time <= to_date)

    sessions = db.exec(base).all()
    plan_map = load_active_plan_map(db, client_ids={s.client_id for s in sessions})

    upcoming = sum(
        1 for s in sessions if as_utc(s.start_time) >= now and s.status == "scheduled"
    )
    completed = sum(1 for s in sessions if s.status == "completed")
    cancelled = sum(1 for s in sessions if s.status == "cancelled")
    no_show = sum(1 for s in sessions if s.status == "no_show")

    # Next upcoming session
    next_session = None
    upcoming_sessions = [
        s for s in sessions if as_utc(s.start_time) >= now and s.status == "scheduled"
    ]
    if upcoming_sessions:
        upcoming_sessions.sort(key=lambda s: as_utc(s.start_time))
        ns = upcoming_sessions[0]
        client = db.get(Client, ns.client_id)
        next_note_map = latest_session_note_by_session_id(
            db,
            therapist_user_id=therapist.user_id,
            session_ids=[ns.id] if ns.id is not None else [],
        )
        next_session = _build_list_item(
            ns,
            client or Client(phone_e164=""),
            preferred_timezone=therapist.preferred_timezone,
            plan_map=plan_map,
            clinical_note=next_note_map.get(ns.id) if ns.id is not None else None,
        )

    return SessionSummary(
        upcoming=upcoming,
        completed=completed,
        cancelled=cancelled,
        no_show=no_show,
        next_session=next_session,
    )


@router.get("/{session_id}", response_model=SessionDetail)
def get_session_detail(
    session_id: int,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
):
    """Get full session detail for calendar drawer."""
    session = db.exec(
        select(TherapySession).where(
            TherapySession.id == session_id,
            TherapySession.therapist_id == therapist.id,
        )
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    client = db.get(Client, session.client_id)

    plan_map = load_active_plan_map(db, client_ids={session.client_id})
    slot_price_map = load_therapist_slot_price_map(db, therapist_ids={session.therapist_id})
    expected_charge_cents, expected_charge_currency, assigned_plan = (
        resolve_expected_charge(
            session,
            plan_map=plan_map,
            slot_price_map=slot_price_map,
        )
    )
    return SessionDetail(
        id=session.id,
        client_name=client.name if client else None,
        client_phone=client.phone_e164 if client else None,
        start_time=to_preferred_timezone(
            session.start_time, therapist.preferred_timezone
        ),
        end_time=to_preferred_timezone(session.end_time, therapist.preferred_timezone),
        duration_minutes=session.duration_minutes,
        status=session.status,
        source=session.source,
        charge_amount_cents=session.charge_amount_cents,
        currency=session.currency,
        expected_charge_cents=expected_charge_cents,
        expected_charge_currency=expected_charge_currency,
        assigned_plan=assigned_plan,
        calendly_event_uri=session.calendly_event_uri,
        created_at=to_preferred_timezone(
            session.created_at, therapist.preferred_timezone
        ),
    )


@router.patch("/{session_id}/status", response_model=SessionStatusUpdateResponse)
def update_session_status(
    session_id: int,
    payload: SessionStatusUpdateRequest,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
):
    """Update a therapist-owned session status, optionally changing duration."""
    session_row = _get_therapist_session_or_404(
        db,
        therapist_id=therapist.id,
        session_id=session_id,
    )

    now = datetime.now(timezone.utc)
    session_row.status = payload.status

    if payload.duration_minutes is not None:
        session_row.duration_minutes = payload.duration_minutes
        session_row.end_time = session_row.start_time + timedelta(
            minutes=payload.duration_minutes
        )

    session_row.updated_at = now
    db.add(session_row)
    db.commit()
    db.refresh(session_row)

    return SessionStatusUpdateResponse(
        session_id=session_row.id,
        status=session_row.status,
        duration_minutes=session_row.duration_minutes,
        updated_at=to_preferred_timezone(
            session_row.updated_at, therapist.preferred_timezone
        ),
    )


@router.put("/{session_id}/clinical-note", response_model=ClinicalNoteResponse)
def upsert_session_clinical_note(
    session_id: int,
    payload: ClinicalNoteUpsertRequest,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
):
    """Create/update therapist clinical note for a session."""
    _get_therapist_session_or_404(db, therapist_id=therapist.id, session_id=session_id)

    merged_note_text, diagnosis = _merge_note_with_diagnosis(
        payload.note_text, payload.diagnosis
    )
    existing = db.exec(
        select(SessionNote)
        .where(
            SessionNote.session_id == session_id,
            SessionNote.author_user_id == therapist.user_id,
        )
        .order_by(SessionNote.created_at.desc())
    ).first()
    now = datetime.now(timezone.utc)
    if existing:
        existing.note_text = merged_note_text
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return _build_clinical_note_response(
            existing, diagnosis=diagnosis, updated_at=now
        )

    note = SessionNote(
        session_id=session_id,
        author_user_id=therapist.user_id,
        note_text=merged_note_text,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _build_clinical_note_response(note, diagnosis=diagnosis)


@router.get("/{session_id}/clinical-note", response_model=ClinicalNoteResponse)
def get_session_clinical_note(
    session_id: int,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
):
    """Fetch therapist-authored clinical note for a session."""
    _get_therapist_session_or_404(db, therapist_id=therapist.id, session_id=session_id)
    note = db.exec(
        select(SessionNote)
        .where(
            SessionNote.session_id == session_id,
            SessionNote.author_user_id == therapist.user_id,
        )
        .order_by(SessionNote.created_at.desc())
    ).first()
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="clinical_note_not_found",
        )
    diagnosis = _extract_diagnosis(_normalize_note_text(note.note_text))
    return _build_clinical_note_response(note, diagnosis=diagnosis)


@router.post(
    "/{session_id}/payment",
    response_model=TherapistRecordPaymentResponse,
    status_code=201,
)
def record_session_payment(
    session_id: int,
    payload: TherapistRecordPaymentRequest,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
):
    """Record payment collected by therapist for a completed session."""
    session_row = _get_therapist_session_or_404(
        db,
        therapist_id=therapist.id,
        session_id=session_id,
    )

    if session_row.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payment_requires_completed_session",
        )

    now = datetime.now(timezone.utc)
    currency = session_row.currency or "HKD"

    payment = PaymentRecord(
        client_id=session_row.client_id,
        source="session_linked",
        session_id=session_row.id,
        amount_cents=payload.amount_cents,
        currency=currency,
        payment_method=payload.method,
        status="pending",
        received_by_role="therapist",
        received_by_name=therapist.display_name,
        paid_at=now,
        notes=payload.notes.strip() if payload.notes else None,
        recorded_by_user_id=therapist.user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(payment)

    db.commit()
    db.refresh(payment)

    return TherapistRecordPaymentResponse(
        payment_id=payment.id,
        session_id=session_row.id,
        amount_cents=payment.amount_cents,
        currency=payment.currency,
        method=payment.payment_method,
        paid_at=to_preferred_timezone(payment.paid_at, therapist.preferred_timezone),
    )
