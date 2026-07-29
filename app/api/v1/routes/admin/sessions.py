"""Admin endpoints for global session management."""

from datetime import datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.v1.schemas.clinical_note import ClinicalNoteResponse, ClinicalNoteUpsertRequest
from app.api.v1.schemas.admin_session import (
    AdminSessionCreateRequest,
    AdminSessionDetailResponse,
    AdminSessionListItem,
    AdminSessionListResponse,
    AdminSessionUpdateRequest,
)
from app.core.auth import get_current_admin
from app.db.session import get_session
from app.models import BillingPlan, Client, ClientPlanAssignment, SessionNote, Therapist, User
from app.models import Session as TherapySession
import logging

from app.core.config import settings
from app.services.calendly import (
    create_event_invitee_with_pat,
    get_event_type_available_times_with_pat,
)
from app.services.timezone_utils import as_utc, normalize_query_datetime, to_preferred_timezone
from app.services.pricing import load_active_plan_map, resolve_expected_charge

logger = logging.getLogger(__name__)

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


def _merge_note_with_diagnosis(
    note_text: str, diagnosis: str | None
) -> tuple[str, str | None]:
    clean_note = _normalize_note_text(note_text.strip())
    if diagnosis is None:
        return clean_note, _extract_diagnosis(clean_note)

    clean_diagnosis = diagnosis.strip()
    if not clean_diagnosis:
        return clean_note, _extract_diagnosis(clean_note)

    if _DIAGNOSIS_PATTERN.search(clean_note):
        merged = _DIAGNOSIS_PATTERN.sub(
            f"Diagnosis: {clean_diagnosis}", clean_note, count=1
        )
    else:
        merged = f"{clean_note}\n\nDiagnosis: {clean_diagnosis}"
    return merged, clean_diagnosis


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


@router.post("", response_model=AdminSessionDetailResponse, status_code=201)
def create_session(
    payload: AdminSessionCreateRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Quick-book a manual session, re-validating the slot against live Calendly availability."""
    # Deferred imports avoid import-order coupling between admin route modules.
    from app.api.v1.routes.admin.therapists import (
        _resolve_active_event_type,
        _resolve_therapist_pat,
    )
    from app.api.v1.routes.webhooks import (
        _notify_booking_confirmed,
        _seed_session_note_from_previous_session,
    )

    client = db.get(Client, payload.client_id)
    if not client:
        raise HTTPException(status_code=404, detail="client_not_found")
    therapist = db.get(Therapist, payload.therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="therapist_not_found")

    start_utc = as_utc(payload.start_time)
    end_utc = start_utc + timedelta(minutes=payload.duration_minutes)

    # Direct-booking exception: sessions for this client bypass Calendly availability
    # and can be placed at any date/time (e.g. ad-hoc / offline-arranged sessions).
    free_booking = "marco" in (client.name or "").strip().lower()

    if not free_booking:
        now = datetime.now(timezone.utc)
        if start_utc <= now:
            raise HTTPException(status_code=409, detail="slot_unavailable")

        event_type = _resolve_active_event_type(db, payload.therapist_id, payload.duration_minutes)
        pat = _resolve_therapist_pat(therapist)

        # Re-validate the chosen instant against live Calendly availability (fail closed).
        available = get_event_type_available_times_with_pat(
            event_type.calendly_event_type_uri, pat, start_utc, end_utc + timedelta(minutes=1)
        )
        slot_is_free = any(
            item.get("start_time")
            and as_utc(datetime.fromisoformat(item["start_time"].replace("Z", "+00:00")))
            == start_utc
            for item in available
        )
        if not slot_is_free:
            raise HTTPException(status_code=409, detail="slot_unavailable")

    start_naive = start_utc.replace(tzinfo=None)
    end_naive = end_utc.replace(tzinfo=None)

    calendly_event_uri: str | None = None
    calendly_invitee_uri: str | None = None
    if not free_booking:
        # In-app overlap guard closes the validate->commit race against other in-app bookings.
        conflict = db.exec(
            select(TherapySession).where(
                TherapySession.therapist_id == payload.therapist_id,
                TherapySession.status != "cancelled",
                TherapySession.start_time < end_naive,
                TherapySession.end_time > start_naive,
            )
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="slot_unavailable")

        # Book the slot on Calendly too (Scheduling API), so it's blocked for
        # outside bookings and lands on the therapist's synced calendars.
        # Best-effort: on failure the session is still created in-app only.
        invitee_resource = create_event_invitee_with_pat(
            event_type.calendly_event_type_uri,
            pat,
            start_utc,
            invitee_name=client.name or "Client",
            invitee_email=(client.email or settings.business_email),
            invitee_timezone=therapist.preferred_timezone,
            invitee_phone_e164=client.phone_e164,
        )
        if invitee_resource:
            calendly_event_uri = invitee_resource.get("event")
            calendly_invitee_uri = invitee_resource.get("uri")
        else:
            logger.warning(
                "Calendly booking failed for quick-book; creating in-app-only session "
                "client_id=%s therapist_id=%s start=%s",
                client.id,
                therapist.id,
                start_utc.isoformat(),
            )

    # The invitee.created webhook can race this request and insert the session
    # first; if it did, adopt that row instead of creating a duplicate.
    session = None
    if calendly_event_uri:
        session = db.exec(
            select(TherapySession).where(
                TherapySession.calendly_event_uri == calendly_event_uri
            )
        ).first()

    if session:
        session.client_id = client.id
        session.therapist_id = therapist.id
        session.start_time = start_naive
        session.end_time = end_naive
        session.duration_minutes = payload.duration_minutes
        session.status = "scheduled"
        session.updated_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()
        db.refresh(session)
    else:
        session = TherapySession(
            client_id=client.id,
            therapist_id=therapist.id,
            start_time=start_naive,
            end_time=end_naive,
            duration_minutes=payload.duration_minutes,
            source="calendly" if calendly_event_uri else "manual",
            status="scheduled",
            calendly_event_uri=calendly_event_uri,
            calendly_invitee_uri=calendly_invitee_uri,
            reminder_sent=False,
            therapist_notified=False,
        )
        db.add(session)
        db.flush()
        _seed_session_note_from_previous_session(
            db, session_row=session, therapist_user_id=therapist.user_id
        )
        db.commit()
        db.refresh(session)

    # Same notifications as a Calendly webhook booking: WhatsApp confirmation to the
    # client and an in-app notification for the therapist.
    _notify_booking_confirmed(db=db, session=session, client=client, therapist=therapist)

    plan_map = load_active_plan_map(db, client_ids={client.id})
    return _build_detail_response(
        session,
        client_name=client.name,
        therapist_name=therapist.display_name,
        preferred_timezone=admin.preferred_timezone,
        plan_map=plan_map,
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
    if (
        "status" not in payload.model_fields_set
        and "billing_plan_id" not in payload.model_fields_set
        and "duration_minutes" not in payload.model_fields_set
    ):
        raise HTTPException(status_code=400, detail="no_changes_requested")

    row = _ensure_session_exists(db, session_id)
    now = datetime.now(timezone.utc)
    previous_status = row.status

    if "status" in payload.model_fields_set and payload.status is not None:
        row.status = payload.status
        row.updated_at = now

    if "duration_minutes" in payload.model_fields_set and payload.duration_minutes is not None:
        row.duration_minutes = payload.duration_minutes
        row.end_time = row.start_time + timedelta(minutes=payload.duration_minutes)
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

    # An admin-initiated cancellation must raise the same notifications a
    # Calendly-initiated one does (req 2.9): therapist bell + admin operations
    # queue. Fires only on the transition into "cancelled", so re-clicking the
    # already-selected status button is a no-op. Never fails the request — the
    # status change is already committed above.
    if row.status == "cancelled" and previous_status != "cancelled" and therapist:
        try:
            _notify_session_cancelled(db=db, session=row, therapist=therapist, client=client)
        except Exception:
            logger.exception(
                "Failed to raise cancellation notifications session_id=%s therapist_id=%s",
                row.id,
                therapist.id,
            )

    plan_map = load_active_plan_map(db, client_ids={row.client_id})
    return _build_detail_response(
        row,
        client_name=client.name if client else None,
        therapist_name=therapist.display_name if therapist else None,
        preferred_timezone=admin.preferred_timezone,
        plan_map=plan_map,
    )


def _notify_session_cancelled(
    *,
    db: Session,
    session: TherapySession,
    therapist: Therapist,
    client: Client | None,
) -> None:
    """Raise therapist + admin-queue notifications for a cancelled session.

    Reuses the webhook helpers so an admin-initiated cancellation is
    indistinguishable from a Calendly-initiated one on every read surface.
    Deferred import mirrors ``create_session`` — it avoids import-order coupling
    between the admin route modules and ``routes.webhooks``.
    """
    from app.api.v1.routes.webhooks import (
        _append_calendly_operational_events,
        _notify_therapist_session_update,
    )

    _notify_therapist_session_update(
        db=db,
        session=session,
        therapist=therapist,
        client=client,
        event_type="therapist.notification.booking_cancelled",
        action="cancelled",
    )
    _append_calendly_operational_events(
        db=db,
        webhook_event_type="invitee.canceled",
        session=session,
        therapist=therapist,
        client=client,
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


@router.put("/{session_id}/clinical-note", response_model=ClinicalNoteResponse)
def upsert_admin_session_clinical_note(
    session_id: int,
    payload: ClinicalNoteUpsertRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ensure_session_exists(db, session_id)
    merged_note_text, diagnosis = _merge_note_with_diagnosis(
        payload.note_text, payload.diagnosis
    )
    existing = db.exec(
        select(SessionNote)
        .where(SessionNote.session_id == session_id)
        .order_by(SessionNote.created_at.desc())
    ).first()
    now = datetime.now(timezone.utc)
    if existing:
        existing.note_text = merged_note_text
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return ClinicalNoteResponse(
            session_id=existing.session_id,
            note_id=existing.id or 0,
            note_text=_normalize_note_text(existing.note_text),
            diagnosis=diagnosis,
            author_user_id=existing.author_user_id,
            created_at=existing.created_at,
            updated_at=now,
        )

    note = SessionNote(
        session_id=session_id,
        author_user_id=admin.id,
        note_text=merged_note_text,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return ClinicalNoteResponse(
        session_id=note.session_id,
        note_id=note.id or 0,
        note_text=_normalize_note_text(note.note_text),
        diagnosis=diagnosis,
        author_user_id=note.author_user_id,
        created_at=note.created_at,
        updated_at=note.created_at,
    )
