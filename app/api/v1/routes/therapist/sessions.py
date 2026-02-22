"""Therapist session endpoints — calendar view and session detail."""

from datetime import datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from app.core.auth import get_current_therapist
from app.db.session import get_session
from app.models import Client, SessionNote, Therapist
from app.models import Session as TherapySession
from app.api.v1.schemas.clinical_note import (
    ClinicalNoteResponse,
    ClinicalNoteUpsertRequest,
)
from app.api.v1.schemas.session import SessionDetail, SessionListItem, SessionSummary
from app.services.pricing import load_active_plan_map, resolve_expected_charge

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
    plan_map: dict[tuple[int, int], dict[str, object]],
) -> SessionListItem:
    expected_charge_cents, expected_charge_currency, assigned_plan = resolve_expected_charge(
        session,
        plan_map=plan_map,
    )
    return SessionListItem(
        id=session.id,
        client_name=client.name,
        client_phone=client.phone_e164,
        start_time=session.start_time,
        end_time=session.end_time,
        duration_minutes=session.duration_minutes,
        status=session.status,
        expected_charge_cents=expected_charge_cents,
        expected_charge_currency=expected_charge_currency,
        assigned_plan=assigned_plan,
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


def _merge_note_with_diagnosis(note_text: str, diagnosis: str | None) -> tuple[str, str | None]:
    clean_note = _normalize_note_text(note_text.strip())
    if diagnosis is None:
        derived = _extract_diagnosis(clean_note)
        return clean_note, derived

    clean_diagnosis = diagnosis.strip()
    if not clean_diagnosis:
        derived = _extract_diagnosis(clean_note)
        return clean_note, derived

    if _DIAGNOSIS_PATTERN.search(clean_note):
        merged = _DIAGNOSIS_PATTERN.sub(f"Diagnosis: {clean_diagnosis}", clean_note, count=1)
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


@router.get("", response_model=list[SessionListItem])
def list_sessions(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
    scope: str | None = Query(None, pattern="^(upcoming|past|all)$"),
    from_date_raw: str | None = Query(None, alias="from"),
    to_date_raw: str | None = Query(None, alias="to"),
):
    """List current therapist's sessions, with optional date range and scope filter."""
    now = datetime.now(timezone.utc)
    from_date = _parse_datetime_query(from_date_raw)
    to_date = _parse_datetime_query(to_date_raw)

    stmt = select(TherapySession).where(
        TherapySession.therapist_id == therapist.id
    )

    # Apply scope filter
    if scope == "upcoming":
        stmt = stmt.where(TherapySession.start_time >= now)
    elif scope == "past":
        stmt = stmt.where(TherapySession.start_time < now)

    # Apply date range filters
    if from_date:
        stmt = stmt.where(TherapySession.start_time >= from_date)
    if to_date:
        stmt = stmt.where(TherapySession.start_time <= to_date)

    stmt = stmt.order_by(TherapySession.start_time)

    sessions = db.exec(stmt).all()

    # Batch-load clients
    client_ids = {s.client_id for s in sessions}
    clients = {}
    if client_ids:
        client_rows = db.exec(
            select(Client).where(Client.id.in_(client_ids))  # type: ignore
        ).all()
        clients = {c.id: c for c in client_rows}

    plan_map = load_active_plan_map(db, client_ids=client_ids)
    return [_build_list_item(s, clients.get(s.client_id, Client(phone_e164="")), plan_map=plan_map) for s in sessions]


@router.get("/summary", response_model=SessionSummary)
def session_summary(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
    from_date_raw: str | None = Query(None, alias="from"),
    to_date_raw: str | None = Query(None, alias="to"),
):
    """Get session counts and next upcoming session."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    from_date = _parse_datetime_query(from_date_raw)
    to_date = _parse_datetime_query(to_date_raw)

    # Base query for this therapist
    base = select(TherapySession).where(
        TherapySession.therapist_id == therapist.id
    )
    if from_date:
        base = base.where(TherapySession.start_time >= from_date)
    if to_date:
        base = base.where(TherapySession.start_time <= to_date)

    sessions = db.exec(base).all()
    plan_map = load_active_plan_map(db, client_ids={s.client_id for s in sessions})

    upcoming = sum(1 for s in sessions if s.start_time >= now and s.status == "scheduled")
    completed = sum(1 for s in sessions if s.status == "completed")
    cancelled = sum(1 for s in sessions if s.status == "cancelled")
    no_show = sum(1 for s in sessions if s.status == "no_show")

    # Next upcoming session
    next_session = None
    upcoming_sessions = [
        s for s in sessions if s.start_time >= now and s.status == "scheduled"
    ]
    if upcoming_sessions:
        upcoming_sessions.sort(key=lambda s: s.start_time)
        ns = upcoming_sessions[0]
        client = db.get(Client, ns.client_id)
        next_session = _build_list_item(ns, client or Client(phone_e164=""), plan_map=plan_map)

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
    expected_charge_cents, expected_charge_currency, assigned_plan = resolve_expected_charge(
        session,
        plan_map=plan_map,
    )
    return SessionDetail(
        id=session.id,
        client_name=client.name if client else None,
        client_phone=client.phone_e164 if client else None,
        start_time=session.start_time,
        end_time=session.end_time,
        duration_minutes=session.duration_minutes,
        status=session.status,
        source=session.source,
        charge_amount_cents=session.charge_amount_cents,
        currency=session.currency,
        expected_charge_cents=expected_charge_cents,
        expected_charge_currency=expected_charge_currency,
        assigned_plan=assigned_plan,
        calendly_event_uri=session.calendly_event_uri,
        created_at=session.created_at,
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

    merged_note_text, diagnosis = _merge_note_with_diagnosis(payload.note_text, payload.diagnosis)
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
        return _build_clinical_note_response(existing, diagnosis=diagnosis, updated_at=now)

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
