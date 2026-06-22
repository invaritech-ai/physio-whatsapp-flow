"""Therapist endpoints for patient visibility."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlmodel import Session, select

from app.api.v1.schemas.therapist_patient import (
    TherapistPatientDetailResponse,
    TherapistPatientListItem,
    TherapistPatientSessionItem,
)
from app.core.auth import get_current_therapist
from app.db.session import get_session
from app.models import Client, Session as TherapySession, Therapist
from app.services.clinical_note_visibility import (
    clinical_note_preview,
    latest_session_note_by_session_id,
)
from app.services.pricing import (
    load_active_plan_map,
    resolve_expected_charge,
)
from app.services.timezone_utils import as_utc, normalize_query_datetime, to_preferred_timezone

router = APIRouter(prefix="/therapist/patients", tags=["Therapist Patients"])


def _ensure_patient_for_therapist(
    db: Session,
    therapist: Therapist,
    client_id: int,
) -> Client:
    session_exists = db.exec(
        select(TherapySession.id).where(
            TherapySession.therapist_id == therapist.id,
            TherapySession.client_id == client_id,
        )
    ).first()
    if not session_exists:
        raise HTTPException(status_code=404, detail="Patient not found")

    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Patient not found")
    return client


def _build_patient_metrics(
    sessions: list[TherapySession],
) -> tuple[int, int, int, datetime | None, datetime | None]:
    now = datetime.now(timezone.utc)
    session_count = len(sessions)
    completed_count = sum(1 for s in sessions if s.status == "completed")
    upcoming = [
        s for s in sessions
        if as_utc(s.start_time) >= now and s.status in {"scheduled", "started"}
    ]
    upcoming_count = len(upcoming)
    last_session_at = max((s.start_time for s in sessions), default=None)
    next_session_at = min((s.start_time for s in upcoming), default=None)
    return session_count, completed_count, upcoming_count, last_session_at, next_session_at


@router.get("", response_model=list[TherapistPatientListItem])
def list_therapist_patients(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List patients associated with the current therapist."""
    client_ids = db.exec(
        select(TherapySession.client_id)
        .where(TherapySession.therapist_id == therapist.id)
        .distinct()
    ).all()

    if not client_ids:
        return []

    stmt = select(Client).where(Client.id.in_(client_ids))  # type: ignore[arg-type]
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Client.name.ilike(like),  # type: ignore[arg-type]
                Client.phone_e164.ilike(like),  # type: ignore[arg-type]
                Client.email.ilike(like),  # type: ignore[arg-type]
            )
        )
    stmt = stmt.order_by(Client.updated_at.desc()).offset(offset).limit(limit)
    clients = db.exec(stmt).all()

    if not clients:
        return []

    scoped_sessions = db.exec(
        select(TherapySession).where(
            TherapySession.therapist_id == therapist.id,
            TherapySession.client_id.in_([c.id for c in clients]),  # type: ignore[arg-type]
        )
    ).all()

    session_map: dict[int, list[TherapySession]] = {}
    for session in scoped_sessions:
        session_map.setdefault(session.client_id, []).append(session)

    rows: list[TherapistPatientListItem] = []
    for client in clients:
        sessions = session_map.get(client.id, [])
        session_count, _, upcoming_count, last_session_at, next_session_at = _build_patient_metrics(sessions)
        rows.append(
            TherapistPatientListItem(
                id=client.id,
                name=client.name,
                phone_e164=client.phone_e164,
                email=client.email,
                date_of_birth=client.date_of_birth,
                address=client.address,
                session_count=session_count,
                upcoming_session_count=upcoming_count,
                last_session_at=(
                    to_preferred_timezone(last_session_at, therapist.preferred_timezone)
                    if last_session_at
                    else None
                ),
                next_session_at=(
                    to_preferred_timezone(next_session_at, therapist.preferred_timezone)
                    if next_session_at
                    else None
                ),
            )
        )

    return rows


@router.get("/{client_id}", response_model=TherapistPatientDetailResponse)
def get_therapist_patient_detail(
    client_id: int,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
):
    """Get patient detail scoped to the current therapist."""
    client = _ensure_patient_for_therapist(db, therapist, client_id)
    sessions = db.exec(
        select(TherapySession).where(
            TherapySession.therapist_id == therapist.id,
            TherapySession.client_id == client_id,
        )
    ).all()
    session_count, completed_count, upcoming_count, last_session_at, next_session_at = _build_patient_metrics(sessions)

    plan_map = load_active_plan_map(db, client_ids={client_id})
    plan_30 = plan_map.get((client_id, 30))
    plan_45 = plan_map.get((client_id, 45))
    return TherapistPatientDetailResponse(
        id=client.id,
        name=client.name,
        phone_e164=client.phone_e164,
        email=client.email,
        date_of_birth=client.date_of_birth,
        address=client.address,
        session_count=session_count,
        completed_session_count=completed_count,
        upcoming_session_count=upcoming_count,
        last_session_at=(
            to_preferred_timezone(last_session_at, therapist.preferred_timezone)
            if last_session_at
            else None
        ),
        next_session_at=(
            to_preferred_timezone(next_session_at, therapist.preferred_timezone)
            if next_session_at
            else None
        ),
        plan_30=plan_30,
        plan_45=plan_45,
    )


@router.get("/{client_id}/sessions", response_model=list[TherapistPatientSessionItem])
def list_therapist_patient_sessions(
    client_id: int,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
    status: str | None = None,
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List sessions for a therapist-scoped patient."""
    _ensure_patient_for_therapist(db, therapist, client_id)

    stmt = select(TherapySession).where(
        TherapySession.therapist_id == therapist.id,
        TherapySession.client_id == client_id,
    )
    if status:
        stmt = stmt.where(TherapySession.status == status)
    from_date = normalize_query_datetime(from_date)
    to_date = normalize_query_datetime(to_date)
    if from_date:
        stmt = stmt.where(TherapySession.start_time >= from_date)
    if to_date:
        stmt = stmt.where(TherapySession.start_time <= to_date)
    stmt = stmt.order_by(TherapySession.start_time.desc()).offset(offset).limit(limit)
    sessions = db.exec(stmt).all()
    plan_map = load_active_plan_map(db, client_ids={client_id})
    session_ids = [s.id for s in sessions if s.id is not None]
    note_map = latest_session_note_by_session_id(
        db,
        therapist_user_id=therapist.user_id,
        session_ids=session_ids,
    )
    rows: list[TherapistPatientSessionItem] = []
    for session in sessions:
        expected_charge_cents, expected_charge_currency, assigned_plan = resolve_expected_charge(
            session,
            plan_map=plan_map,
        )
        note = note_map.get(session.id) if session.id is not None else None
        rows.append(
            TherapistPatientSessionItem(
                id=session.id,
                start_time=to_preferred_timezone(session.start_time, therapist.preferred_timezone),
                end_time=to_preferred_timezone(session.end_time, therapist.preferred_timezone),
                duration_minutes=session.duration_minutes,
                status=session.status,
                source=session.source,
                charge_amount_cents=session.charge_amount_cents,
                currency=session.currency,
                expected_charge_cents=expected_charge_cents,
                expected_charge_currency=expected_charge_currency,
                assigned_plan=assigned_plan,
                has_clinical_note=note is not None,
                clinical_note_preview=clinical_note_preview(note.note_text) if note else None,
                clinical_note_saved_at=(
                    to_preferred_timezone(note.created_at, therapist.preferred_timezone)
                    if note
                    else None
                ),
            )
        )
    return rows
