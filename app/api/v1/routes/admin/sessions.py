"""Admin endpoints for global session management."""

from datetime import datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.v1.schemas.clinical_note import ClinicalNoteResponse
from app.api.v1.schemas.admin_session import (
    AdminSessionDetailResponse,
    AdminSessionListItem,
    AdminSessionListResponse,
    AdminSessionUpdateRequest,
)
from app.core.auth import get_current_admin
from app.db.session import get_session
from app.models import BillingPlan, Client, ClientPlanAssignment, SessionNote, Therapist, User
from app.models import Session as TherapySession
from app.services.timezone_utils import normalize_query_datetime, to_preferred_timezone
from app.services.pricing import load_active_plan_map, resolve_expected_charge

router = APIRouter(prefix="/admin/sessions", tags=["Admin - Sessions"])
_DIAGNOSIS_PATTERN = re.compile(r"diagnosis\s*:\s*(.+)", re.IGNORECASE)


def _ensure_session_exists(db: Session, session_id: int) -> TherapySession:
    row = db.get(TherapySession, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="session_not_found")
    return row


def _ensure_plan_exists(db: Session, plan_id: int) -> BillingPlan:
    plan = db.get(BillingPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="plan_not_found")
    return plan


def _build_list_item(
    row: TherapySession,
    *,
    client_name: str | None,
    therapist_name: str | None,
    preferred_timezone: str | None,
    plan_map: dict[tuple[int, int], dict[str, object]],
) -> AdminSessionListItem:
    expected_charge_cents, expected_charge_currency, assigned_plan = resolve_expected_charge(
        row,
        plan_map=plan_map,
    )
    return AdminSessionListItem(
        id=row.id,
        client_id=row.client_id,
        client_name=client_name,
        therapist_id=row.therapist_id,
        therapist_name=therapist_name,
        start_time=to_preferred_timezone(row.start_time, preferred_timezone),
        end_time=to_preferred_timezone(row.end_time, preferred_timezone),
        duration_minutes=row.duration_minutes,
        status=row.status,
        source=row.source,
        charge_amount_cents=row.charge_amount_cents,
        currency=row.currency,
        expected_charge_cents=expected_charge_cents,
        expected_charge_currency=expected_charge_currency,
        assigned_plan=assigned_plan,
    )


def _build_detail_response(
    row: TherapySession,
    *,
    client_name: str | None,
    therapist_name: str | None,
    preferred_timezone: str | None,
    plan_map: dict[tuple[int, int], dict[str, object]],
) -> AdminSessionDetailResponse:
    expected_charge_cents, expected_charge_currency, assigned_plan = resolve_expected_charge(
        row,
        plan_map=plan_map,
    )
    return AdminSessionDetailResponse(
        id=row.id,
        client_id=row.client_id,
        client_name=client_name,
        therapist_id=row.therapist_id,
        therapist_name=therapist_name,
        start_time=to_preferred_timezone(row.start_time, preferred_timezone),
        end_time=to_preferred_timezone(row.end_time, preferred_timezone),
        duration_minutes=row.duration_minutes,
        status=row.status,
        source=row.source,
        charge_amount_cents=row.charge_amount_cents,
        currency=row.currency,
        expected_charge_cents=expected_charge_cents,
        expected_charge_currency=expected_charge_currency,
        assigned_plan=assigned_plan,
        calendly_event_uri=row.calendly_event_uri,
        calendly_invitee_uri=row.calendly_invitee_uri,
        created_at=to_preferred_timezone(row.created_at, preferred_timezone),
        updated_at=to_preferred_timezone(row.updated_at, preferred_timezone),
    )


def _extract_diagnosis(note_text: str) -> str | None:
    match = _DIAGNOSIS_PATTERN.search(note_text)
    if not match:
        return None
    return match.group(1).strip() or None


def _normalize_note_text(note_text: str) -> str:
    normalized = note_text.replace("\r\n", "\n").replace("\r", "\n")
    if "\\n" in normalized:
        normalized = normalized.replace("\\n", "\n")
    return normalized


def _build_clinical_note_response(note: SessionNote) -> ClinicalNoteResponse:
    normalized_note_text = _normalize_note_text(note.note_text)
    diagnosis = _extract_diagnosis(normalized_note_text)
    return ClinicalNoteResponse(
        session_id=note.session_id,
        note_id=note.id or 0,
        note_text=normalized_note_text,
        diagnosis=diagnosis,
        author_user_id=note.author_user_id,
        created_at=note.created_at,
        updated_at=note.created_at,
    )


@router.get("", response_model=AdminSessionListResponse)
def list_sessions(
    status: str | None = Query(
        default=None,
        pattern="^(scheduled|started|completed|cancelled|no_show)$",
    ),
    therapist_id: int | None = None,
    client_id: int | None = None,
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    from_date = normalize_query_datetime(from_date)
    to_date = normalize_query_datetime(to_date)
    filters = []
    if status:
        filters.append(TherapySession.status == status)
    if therapist_id is not None:
        filters.append(TherapySession.therapist_id == therapist_id)
    if client_id is not None:
        filters.append(TherapySession.client_id == client_id)
    if from_date:
        filters.append(TherapySession.start_time >= from_date)
    if to_date:
        filters.append(TherapySession.start_time <= to_date)

    total_stmt = select(func.count()).select_from(TherapySession)
    items_stmt = select(TherapySession)
    for condition in filters:
        total_stmt = total_stmt.where(condition)
        items_stmt = items_stmt.where(condition)

    total = db.exec(total_stmt).one()
    rows = db.exec(
        items_stmt.order_by(TherapySession.start_time.desc(), TherapySession.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    client_map: dict[int, Client] = {}
    therapist_map: dict[int, Therapist] = {}
    client_ids = {row.client_id for row in rows}
    therapist_ids = {row.therapist_id for row in rows}
    if client_ids:
        client_rows = db.exec(
            select(Client).where(Client.id.in_(client_ids))  # type: ignore[arg-type]
        ).all()
        client_map = {item.id: item for item in client_rows}
    if therapist_ids:
        therapist_rows = db.exec(
            select(Therapist).where(Therapist.id.in_(therapist_ids))  # type: ignore[arg-type]
        ).all()
        therapist_map = {item.id: item for item in therapist_rows}

    plan_map = load_active_plan_map(db, client_ids=client_ids)
    items = [
        _build_list_item(
            row,
            client_name=client_map.get(row.client_id).name if client_map.get(row.client_id) else None,
            therapist_name=therapist_map.get(row.therapist_id).display_name if therapist_map.get(row.therapist_id) else None,
            preferred_timezone=admin.preferred_timezone,
            plan_map=plan_map,
        )
        for row in rows
    ]
    return AdminSessionListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(items)) < total,
    )


@router.get("/{session_id}", response_model=AdminSessionDetailResponse)
def get_session_detail(
    session_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    row = _ensure_session_exists(db, session_id)
    client = db.get(Client, row.client_id)
    therapist = db.get(Therapist, row.therapist_id)
    plan_map = load_active_plan_map(db, client_ids={row.client_id})
    return _build_detail_response(
        row,
        client_name=client.name if client else None,
        therapist_name=therapist.display_name if therapist else None,
        preferred_timezone=admin.preferred_timezone,
        plan_map=plan_map,
    )


@router.put("/{session_id}", response_model=AdminSessionDetailResponse)
def update_session(
    session_id: int,
    payload: AdminSessionUpdateRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    if admin.id is None:
        raise HTTPException(status_code=403, detail="access_denied")
    if not payload.model_fields_set:
        raise HTTPException(status_code=400, detail="no_changes_requested")
    if "status" not in payload.model_fields_set and "billing_plan_id" not in payload.model_fields_set:
        raise HTTPException(status_code=400, detail="no_changes_requested")

    row = _ensure_session_exists(db, session_id)
    now = datetime.now(timezone.utc)

    if "status" in payload.model_fields_set and payload.status is not None:
        row.status = payload.status
        row.updated_at = now

    if "billing_plan_id" in payload.model_fields_set and payload.billing_plan_id is not None:
        plan = _ensure_plan_exists(db, payload.billing_plan_id)
        if plan.duration_minutes != row.duration_minutes:
            # Sync session duration to the chosen plan so downstream billing
            # (expected charge, receipts) reflects the actual delivered length.
            row.duration_minutes = plan.duration_minutes
            row.end_time = row.start_time + timedelta(minutes=plan.duration_minutes)
            row.updated_at = now

        existing_assignment = db.exec(
            select(ClientPlanAssignment).where(
                ClientPlanAssignment.client_id == row.client_id,
                ClientPlanAssignment.duration_minutes == row.duration_minutes,
            )
        ).first()
        if existing_assignment:
            existing_assignment.billing_plan_id = payload.billing_plan_id
            existing_assignment.assigned_by_user_id = admin.id
            existing_assignment.effective_from = payload.plan_effective_from or now
            if "plan_notes" in payload.model_fields_set:
                existing_assignment.notes = payload.plan_notes
            existing_assignment.is_active = True
            existing_assignment.updated_at = now
            db.add(existing_assignment)
        else:
            db.add(
                ClientPlanAssignment(
                    client_id=row.client_id,
                    duration_minutes=row.duration_minutes,
                    billing_plan_id=payload.billing_plan_id,
                    assigned_by_user_id=admin.id,
                    effective_from=payload.plan_effective_from or now,
                    notes=payload.plan_notes if "plan_notes" in payload.model_fields_set else None,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )

    db.add(row)
    db.commit()
    db.refresh(row)

    client = db.get(Client, row.client_id)
    therapist = db.get(Therapist, row.therapist_id)
    plan_map = load_active_plan_map(db, client_ids={row.client_id})
    return _build_detail_response(
        row,
        client_name=client.name if client else None,
        therapist_name=therapist.display_name if therapist else None,
        preferred_timezone=admin.preferred_timezone,
        plan_map=plan_map,
    )


@router.get("/{session_id}/clinical-note", response_model=ClinicalNoteResponse)
def get_admin_session_clinical_note(
    session_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    session_row = _ensure_session_exists(db, session_id)
    note = db.exec(
        select(SessionNote)
        .where(SessionNote.session_id == session_id)
        .order_by(SessionNote.created_at.desc())
    ).first()
    if not note:
        # For admin session workflows, absence of a clinical note is a valid
        # empty state and should not hard-fail the entire session details flow.
        fallback_ts = session_row.updated_at or session_row.created_at
        return ClinicalNoteResponse(
            session_id=session_id,
            note_id=0,
            note_text="",
            diagnosis=None,
            author_user_id=0,
            created_at=fallback_ts,
            updated_at=fallback_ts,
        )
    return _build_clinical_note_response(note)
