"""Therapist session endpoints — calendar view and session detail."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from app.core.auth import get_current_therapist
from app.db.session import get_session
from app.models import Client, Therapist
from app.models import Session as TherapySession
from app.api.v1.schemas.session import SessionDetail, SessionListItem, SessionSummary

router = APIRouter(prefix="/sessions", tags=["Therapist Sessions"])


def _build_list_item(session: TherapySession, client: Client) -> SessionListItem:
    return SessionListItem(
        id=session.id,
        client_name=client.name,
        client_phone=client.phone_e164,
        start_time=session.start_time,
        end_time=session.end_time,
        duration_minutes=session.duration_minutes,
        status=session.status,
    )


@router.get("", response_model=list[SessionListItem])
def list_sessions(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
    scope: str | None = Query(None, pattern="^(upcoming|past|all)$"),
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
):
    """List current therapist's sessions, with optional date range and scope filter."""
    now = datetime.now(timezone.utc)

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

    return [
        _build_list_item(s, clients.get(s.client_id, Client(phone_e164="")))
        for s in sessions
    ]


@router.get("/summary", response_model=SessionSummary)
def session_summary(
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
):
    """Get session counts and next upcoming session."""
    now = datetime.now(timezone.utc)

    # Base query for this therapist
    base = select(TherapySession).where(
        TherapySession.therapist_id == therapist.id
    )
    if from_date:
        base = base.where(TherapySession.start_time >= from_date)
    if to_date:
        base = base.where(TherapySession.start_time <= to_date)

    sessions = db.exec(base).all()

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
        next_session = _build_list_item(ns, client or Client(phone_e164=""))

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
        calendly_event_uri=session.calendly_event_uri,
        created_at=session.created_at,
    )
