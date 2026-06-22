"""Admin endpoints for managing therapists."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, func, select

from app.core.auth import get_current_admin, is_bot_only_suspend_email
from app.core.config import settings
from app.core.encryption import decrypt_string, encrypt_string
from app.db.session import get_session
from app.models import Therapist, TherapistEventType, TherapistSpecialty, TherapistSpecialtyMap, User
from app.api.v1.schemas.admin_session import (
    AdminAvailableTimeSlot,
    AdminAvailableTimesResponse,
)
from app.api.v1.schemas.therapist_onboarding import (
    CalendlyWebhookCheckResponse,
    ValidateCalendlyRequest,
    ValidateCalendlyResponse,
)
from app.api.v1.routes.therapist.onboarding import (
    _build_validate_calendly_response,
    _normalize_slot_mapping_entry,
)
from app.services.calendly import get_event_type_available_times_with_pat
from app.services.timezone_utils import as_utc
from app.api.v1.schemas.therapist import (
    AdminSlotMappingUpdateRequest,
    AdminValidateCalendlyForTherapistRequest,
    TherapistCreate,
    TherapistUpdate,
    TherapistResponse,
    TherapistListResponse,
    SpecialtyAssignment,
)
from app.api.v1.schemas.therapist_onboarding import SlotMappingInfo
from app.api.v1.schemas.specialty import SpecialtyResponse
from app.services.calendly_webhooks import CalendlyWebhookError, check_webhook_registration
from app.services.license_numbers import is_valid_license_number, normalize_license_number
from app.services.therapist_onboarding import sync_event_types, validate_calendly_pat

router = APIRouter(prefix="/admin/therapists", tags=["Admin - Therapists"])


def _normalize_and_validate_license_number(license_number: str | None) -> str | None:
    normalized = normalize_license_number(license_number)
    if normalized is None:
        return None
    if not is_valid_license_number(normalized):
        raise HTTPException(status_code=400, detail="invalid_license_number")
    return normalized


def _ensure_unique_license_number(
    db: Session,
    license_number: str | None,
    *,
    ignore_therapist_id: int | None = None,
) -> None:
    if license_number is None:
        return
    existing = db.exec(
        select(Therapist).where(Therapist.license_number == license_number)
    ).first()
    if existing and existing.id != ignore_therapist_id:
        raise HTTPException(status_code=400, detail="license_number_already_exists")


def _calendly_event_lookups(validation_data: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    """Build scheduling-url and event-type-uri lookups from validated Calendly events."""
    url_to_event_type: dict[str, dict] = {}
    uri_to_event_type: dict[str, dict] = {}
    for et in validation_data["event_types"]:
        uri = (et.get("calendly_event_type_uri") or "").rstrip("/")
        if uri and uri not in uri_to_event_type:
            uri_to_event_type[uri] = et
        url = (et.get("scheduling_url") or "").rstrip("/")
        if url and url not in url_to_event_type:
            url_to_event_type[url] = et
    return url_to_event_type, uri_to_event_type


def _persist_slot_mapping_simple(
    db: Session,
    therapist: Therapist,
    *,
    slot_mapping: dict[str, str],
    slot_payouts: dict[str, int] | None = None,
) -> list[TherapistEventType]:
    """Replace a therapist's event types from raw booking links + optional
    therapist payouts, without a Calendly PAT. Preserves the Calendly event-type
    URI for links that are unchanged from the existing mapping.
    """
    existing = db.exec(
        select(TherapistEventType).where(TherapistEventType.therapist_id == therapist.id)
    ).all()
    uri_by_url = {
        (et.scheduling_url or "").rstrip("/"): et.calendly_event_type_uri
        for et in existing
        if et.scheduling_url
    }
    for et in existing:
        db.delete(et)
    db.flush()

    payouts = slot_payouts or {}
    created: list[TherapistEventType] = []
    for duration_str, raw_url in slot_mapping.items():
        link = (raw_url or "").strip()
        if not link:
            continue
        row = TherapistEventType(
            therapist_id=therapist.id,
            calendly_event_type_uri=uri_by_url.get(link.rstrip("/")),
            duration_minutes=int(duration_str),
            scheduling_url=link,
            is_active=True,
            payout_cents=payouts.get(duration_str),
        )
        db.add(row)
        created.append(row)
    return created


def _persist_slot_mapping_with_prices(
    db: Session,
    therapist: Therapist,
    *,
    slot_mapping: dict[str, str],
    validation_data: dict,
    slot_payouts: dict[str, int] | None = None,
) -> list[TherapistEventType]:
    """Replace a therapist's event types from a {duration: scheduling_url} map, with
    optional therapist payouts. Resolves event-type URIs against validated events.
    """
    url_to_event_type, uri_to_event_type = _calendly_event_lookups(validation_data)
    existing = db.exec(
        select(TherapistEventType).where(TherapistEventType.therapist_id == therapist.id)
    ).all()
    for et in existing:
        db.delete(et)
    db.flush()

    payouts = slot_payouts or {}
    created: list[TherapistEventType] = []
    for duration_str, mapping_value in slot_mapping.items():
        scheduling_url, calendly_event_type_uri = _normalize_slot_mapping_entry(
            mapping_value,
            url_to_event_type=url_to_event_type,
            uri_to_event_type=uri_to_event_type,
        )
        row = TherapistEventType(
            therapist_id=therapist.id,
            calendly_event_type_uri=calendly_event_type_uri,
            duration_minutes=int(duration_str),
            scheduling_url=scheduling_url,
            is_active=True,
            payout_cents=payouts.get(duration_str),
        )
        db.add(row)
        created.append(row)
    return created


def _persist_slot_durations(
    db: Session,
    therapist: Therapist,
    *,
    slot_durations: list[str],
    slot_payouts: dict[str, int] | None = None,
) -> list[TherapistEventType]:
    """Record the session lengths a therapist offers (+ optional payout) without a
    booking link yet. The scheduling_url is filled in later from the edit screen.
    Replaces the therapist's existing event types.
    """
    existing = db.exec(
        select(TherapistEventType).where(TherapistEventType.therapist_id == therapist.id)
    ).all()
    for et in existing:
        db.delete(et)
    db.flush()

    payouts = slot_payouts or {}
    created: list[TherapistEventType] = []
    seen: set[int] = set()
    for duration_str in slot_durations:
        try:
            duration = int(duration_str)
        except (TypeError, ValueError):
            continue
        if duration in seen:
            continue
        seen.add(duration)
        row = TherapistEventType(
            therapist_id=therapist.id,
            calendly_event_type_uri=None,
            duration_minutes=duration,
            scheduling_url=None,
            is_active=True,
            payout_cents=payouts.get(duration_str),
        )
        db.add(row)
        created.append(row)
    return created


@router.post("/validate-calendly", response_model=ValidateCalendlyResponse)
def admin_validate_calendly(
    data: ValidateCalendlyRequest,
    admin: User = Depends(get_current_admin),
):
    """Validate a Calendly PAT and preview its event types (admin create flow)."""
    _ = admin
    valid, validation_data, errors = validate_calendly_pat(data.calendly_pat)
    if not valid:
        raise HTTPException(status_code=400, detail=errors[0] if errors else "Invalid Calendly token")
    return _build_validate_calendly_response(validation_data)


@router.post("", response_model=TherapistResponse, status_code=201)
def create_therapist(data: TherapistCreate, admin: User = Depends(get_current_admin), db: Session = Depends(get_session)):
    """
    Create a new therapist (with associated User record).

    Creates both User and Therapist records atomically.
    """
    # Check if email already exists
    existing_user = db.exec(select(User).where(User.email == data.email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    license_number = _normalize_and_validate_license_number(data.license_number)
    _ensure_unique_license_number(db, license_number)

    # Admin-provisioned therapists may omit neon_auth_sub; use a pending sentinel
    # keyed by email. On first Neon login, auth links the real sub to this record
    # (see get_current_approved_user). Email uniqueness keeps the sentinel unique.
    neon_auth_sub = data.neon_auth_sub or f"pending:{data.email.strip().lower()}"

    # Create User record
    user = User(
        neon_auth_sub=neon_auth_sub,
        email=data.email,
        display_name=data.display_name,
        role="therapist",
        is_active=True,
    )
    db.add(user)
    db.flush()  # Get user.id without committing

    # Create Therapist record
    therapist = Therapist(
        user_id=user.id,
        display_name=data.display_name,
        license_number=license_number,
        calendly_user_uri=data.calendly_user_uri,
        is_female=data.is_female,
        is_active=True,
    )
    db.add(therapist)
    db.flush()  # Assign therapist.id before optional Calendly setup

    # Optional Calendly PAT — when given, validate + store it (enables live
    # availability) and resolve event-type URIs. Not required: slot mapping +
    # pricing can be set from booking links alone.
    if data.calendly_pat:
        pat = data.calendly_pat.strip()
        valid, validation_data, errors = validate_calendly_pat(pat)
        if not valid:
            db.rollback()
            raise HTTPException(status_code=400, detail=errors[0] if errors else "invalid_calendly_token")
        therapist.calendly_user_uri = validation_data["user_uri"]
        therapist.calendly_pat_encrypted = encrypt_string(pat)
        db.add(therapist)
        if data.slot_mapping:
            try:
                _persist_slot_mapping_with_prices(
                    db, therapist,
                    slot_mapping=data.slot_mapping,
                    validation_data=validation_data,
                    slot_payouts=data.slot_payouts,
                )
            except HTTPException:
                db.rollback()
                raise
        elif data.slot_durations:
            # Verified the token but the admin chose offered durations (no links yet).
            # Keep that selection; booking links are added later from the edit screen.
            _persist_slot_durations(
                db, therapist,
                slot_durations=data.slot_durations,
                slot_payouts=data.slot_payouts,
            )
        else:
            _, sync_errors = sync_event_types(db, therapist, calendly_pat=pat)
            if sync_errors:
                db.rollback()
                raise HTTPException(status_code=400, detail=sync_errors[0])
    elif data.slot_mapping:
        # No PAT: persist booking links + payouts directly.
        _persist_slot_mapping_simple(
            db, therapist,
            slot_mapping=data.slot_mapping,
            slot_payouts=data.slot_payouts,
        )
    elif data.slot_durations:
        # No PAT and no links yet: record the offered session lengths (+ optional
        # payout). Booking links are added later from the therapist's edit screen.
        _persist_slot_durations(
            db, therapist,
            slot_durations=data.slot_durations,
            slot_payouts=data.slot_payouts,
        )

    db.commit()
    db.refresh(therapist)

    # Return with empty specialties list
    return TherapistResponse(
        id=therapist.id,
        user_id=therapist.user_id,
        display_name=therapist.display_name,
        license_number=therapist.license_number,
        is_active=therapist.is_active,
        is_female=therapist.is_female,
        calendly_user_uri=therapist.calendly_user_uri,
        specialties=[],
        created_at=therapist.created_at,
    )


@router.get("", response_model=list[TherapistListResponse])
def list_therapists(admin: User = Depends(get_current_admin), db: Session = Depends(get_session)):
    """List all therapists with basic info."""
    stmt = select(Therapist, User).join(User).order_by(Therapist.created_at.desc())
    results = db.exec(stmt).all()
    therapist_ids = [therapist.id for therapist, _ in results if therapist.id is not None]
    specialty_count_map: dict[int, int] = {}
    if therapist_ids:
        specialty_count_rows = db.exec(
            select(
                TherapistSpecialtyMap.therapist_id,
                func.count(TherapistSpecialtyMap.id),
            )
            .where(  # type: ignore[arg-type]
                TherapistSpecialtyMap.therapist_id.in_(therapist_ids)
            )
            .group_by(TherapistSpecialtyMap.therapist_id)
        ).all()
        specialty_count_map = {
            therapist_id: int(count)
            for therapist_id, count in specialty_count_rows
        }

    therapists = []
    for therapist, user in results:
        therapists.append(
            TherapistListResponse(
                id=therapist.id,
                display_name=therapist.display_name,
                license_number=therapist.license_number,
                is_active=therapist.is_active,
                email=user.email,
                specialty_count=specialty_count_map.get(therapist.id, 0),
                is_bot_only_suspend=is_bot_only_suspend_email(user.email),
            )
        )

    return therapists


@router.get("/{therapist_id}", response_model=TherapistResponse)
def get_therapist(therapist_id: int, admin: User = Depends(get_current_admin), db: Session = Depends(get_session)):
    """Get therapist detail with specialties."""
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")

    # Get specialties
    stmt = (
        select(TherapistSpecialty)
        .join(TherapistSpecialtyMap)
        .where(TherapistSpecialtyMap.therapist_id == therapist_id)
    )
    specialties = db.exec(stmt).all()

    return TherapistResponse(
        id=therapist.id,
        user_id=therapist.user_id,
        display_name=therapist.display_name,
        license_number=therapist.license_number,
        is_active=therapist.is_active,
        is_female=therapist.is_female,
        calendly_user_uri=therapist.calendly_user_uri,
        specialties=[
            SpecialtyResponse(
                id=s.id, name=s.name, description=s.description, is_active=s.is_active
            )
            for s in specialties
        ],
        created_at=therapist.created_at,
    )


@router.get("/{therapist_id}/slots", response_model=list[SlotMappingInfo])
def get_therapist_slots(therapist_id: int, admin: User = Depends(get_current_admin), db: Session = Depends(get_session)):
    """Get active booking slots (scheduling URLs) for a therapist."""
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")

    event_types = db.exec(
        select(TherapistEventType)
        .where(TherapistEventType.therapist_id == therapist_id, TherapistEventType.is_active == True)  # noqa: E712
        .order_by(TherapistEventType.duration_minutes)
    ).all()

    return [
        SlotMappingInfo(
            duration_minutes=et.duration_minutes,
            scheduling_url=et.scheduling_url,
            calendly_event_type_uri=et.calendly_event_type_uri,
            payout_cents=et.payout_cents,
        )
        for et in event_types
    ]


@router.post("/{therapist_id}/validate-calendly", response_model=ValidateCalendlyResponse)
def admin_validate_calendly_for_therapist(
    therapist_id: int,
    data: AdminValidateCalendlyForTherapistRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Validate a therapist's Calendly (stored PAT by default) and preview event types."""
    _ = admin
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")
    pat = (data.calendly_pat or "").strip() or _resolve_therapist_pat(therapist)
    valid, validation_data, errors = validate_calendly_pat(pat)
    if not valid:
        raise HTTPException(status_code=400, detail=errors[0] if errors else "Invalid Calendly token")
    return _build_validate_calendly_response(validation_data)


@router.put("/{therapist_id}/slot-mapping", response_model=list[SlotMappingInfo])
def admin_update_slot_mapping(
    therapist_id: int,
    data: AdminSlotMappingUpdateRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Admin: replace a therapist's booking-link slot mapping and per-slot prices."""
    _ = admin
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")

    provided_pat = (data.calendly_pat or "").strip()
    if provided_pat:
        # PAT given: validate, store it, and resolve event-type URIs from Calendly.
        valid, validation_data, errors = validate_calendly_pat(provided_pat)
        if not valid:
            raise HTTPException(status_code=400, detail=errors[0] if errors else "Invalid Calendly token")
        therapist.calendly_user_uri = validation_data["user_uri"]
        therapist.calendly_pat_encrypted = encrypt_string(provided_pat)
        db.add(therapist)
        try:
            created = _persist_slot_mapping_with_prices(
                db, therapist,
                slot_mapping=data.slot_mapping,
                validation_data=validation_data,
                slot_payouts=data.slot_payouts,
            )
        except HTTPException:
            db.rollback()
            raise
    else:
        # No PAT: persist booking links + prices + payouts directly.
        created = _persist_slot_mapping_simple(
            db, therapist,
            slot_mapping=data.slot_mapping,
            slot_payouts=data.slot_payouts,
        )

    db.commit()
    return [
        SlotMappingInfo(
            duration_minutes=et.duration_minutes,
            scheduling_url=et.scheduling_url,
            calendly_event_type_uri=et.calendly_event_type_uri,
            payout_cents=et.payout_cents,
        )
        for et in sorted(created, key=lambda e: e.duration_minutes)
    ]


def _resolve_active_event_type(
    db: Session, therapist_id: int, duration_minutes: int
) -> TherapistEventType:
    """Return the active event type for a therapist+duration, or raise 409."""
    event_type = db.exec(
        select(TherapistEventType).where(
            TherapistEventType.therapist_id == therapist_id,
            TherapistEventType.duration_minutes == duration_minutes,
            TherapistEventType.is_active == True,  # noqa: E712
        )
    ).first()
    if not event_type or not event_type.calendly_event_type_uri:
        raise HTTPException(status_code=409, detail="event_type_not_configured")
    return event_type


def _resolve_therapist_pat(therapist: Therapist) -> str:
    """Decrypt the therapist's stored Calendly PAT, or raise 400 if unset."""
    if not therapist.calendly_pat_encrypted:
        raise HTTPException(status_code=400, detail="calendly_pat_missing")
    return decrypt_string(therapist.calendly_pat_encrypted)


@router.get("/{therapist_id}/available-times", response_model=AdminAvailableTimesResponse)
def get_therapist_available_times(
    therapist_id: int,
    duration_minutes: int = Query(..., gt=0),
    start: datetime = Query(..., description="Window start (UTC ISO, aware)"),
    end: datetime = Query(..., description="Window end (UTC ISO, aware)"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Fetch live Calendly availability for a therapist + duration within a window."""
    _ = admin
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")

    event_type = _resolve_active_event_type(db, therapist_id, duration_minutes)
    pat = _resolve_therapist_pat(therapist)

    # Normalize to aware UTC and clamp to a valid Calendly window (future, <= 7 days).
    now = datetime.now(timezone.utc)
    start_utc = as_utc(start)
    end_utc = as_utc(end)
    if start_utc < now:
        start_utc = now + timedelta(minutes=1)
    if end_utc <= start_utc:
        end_utc = start_utc + timedelta(days=1)
    max_end = start_utc + timedelta(days=7)
    if end_utc > max_end:
        end_utc = max_end

    raw_slots = get_event_type_available_times_with_pat(
        event_type.calendly_event_type_uri, pat, start_utc, end_utc
    )

    slots: list[AdminAvailableTimeSlot] = []
    for item in raw_slots:
        raw_start = item.get("start_time")
        if not raw_start:
            continue
        slot_start = as_utc(datetime.fromisoformat(raw_start.replace("Z", "+00:00")))
        slots.append(
            AdminAvailableTimeSlot(
                start_time=slot_start,
                end_time=slot_start + timedelta(minutes=duration_minutes),
                scheduling_url=item.get("scheduling_url"),
            )
        )

    return AdminAvailableTimesResponse(
        therapist_id=therapist_id,
        duration_minutes=duration_minutes,
        calendly_event_type_uri=event_type.calendly_event_type_uri,
        slots=slots,
    )


@router.patch("/{therapist_id}", response_model=TherapistResponse)
def update_therapist(
    therapist_id: int, data: TherapistUpdate, admin: User = Depends(get_current_admin), db: Session = Depends(get_session)
):
    """Update therapist details."""
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")

    # Update fields if provided
    if data.display_name is not None:
        therapist.display_name = data.display_name
    if "license_number" in data.model_fields_set:
        normalized_license = _normalize_and_validate_license_number(data.license_number)
        _ensure_unique_license_number(
            db,
            normalized_license,
            ignore_therapist_id=therapist.id,
        )
        therapist.license_number = normalized_license
    if data.is_active is not None:
        therapist.is_active = data.is_active
    if data.is_female is not None:
        therapist.is_female = data.is_female
    if data.calendly_user_uri is not None:
        therapist.calendly_user_uri = data.calendly_user_uri

    db.add(therapist)
    db.commit()
    db.refresh(therapist)

    # Return full response with specialties
    return get_therapist(therapist_id=therapist_id, admin=admin, db=db)


@router.delete("/{therapist_id}", status_code=204)
def delete_therapist(therapist_id: int, admin: User = Depends(get_current_admin), db: Session = Depends(get_session)):
    """Soft-delete therapist (set is_active=false)."""
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")

    therapist.is_active = False
    db.add(therapist)
    db.commit()
    return None


# Specialty Assignment Endpoints


@router.post("/{therapist_id}/specialties", status_code=201)
def assign_specialty(
    therapist_id: int, data: SpecialtyAssignment, admin: User = Depends(get_current_admin), db: Session = Depends(get_session)
):
    """Assign a specialty to a therapist."""
    # Verify therapist exists
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")

    # Verify specialty exists
    specialty = db.get(TherapistSpecialty, data.specialty_id)
    if not specialty:
        raise HTTPException(status_code=404, detail="Specialty not found")

    # Check if already assigned
    existing = db.exec(
        select(TherapistSpecialtyMap).where(
            TherapistSpecialtyMap.therapist_id == therapist_id,
            TherapistSpecialtyMap.specialty_id == data.specialty_id,
        )
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Specialty already assigned")

    # Create assignment
    assignment = TherapistSpecialtyMap(
        therapist_id=therapist_id, specialty_id=data.specialty_id
    )
    db.add(assignment)
    db.commit()

    return {"status": "success", "message": "Specialty assigned"}


@router.delete("/{therapist_id}/specialties/{specialty_id}", status_code=204)
def remove_specialty(
    therapist_id: int, specialty_id: int, admin: User = Depends(get_current_admin), db: Session = Depends(get_session)
):
    """Remove a specialty from a therapist."""
    assignment = db.exec(
        select(TherapistSpecialtyMap).where(
            TherapistSpecialtyMap.therapist_id == therapist_id,
            TherapistSpecialtyMap.specialty_id == specialty_id,
        )
    ).first()

    if not assignment:
        raise HTTPException(status_code=404, detail="Specialty assignment not found")

    db.delete(assignment)
    db.commit()
    return None


@router.get("/{therapist_id}/specialties", response_model=list[SpecialtyResponse])
def list_therapist_specialties(therapist_id: int, admin: User = Depends(get_current_admin), db: Session = Depends(get_session)):
    """List all specialties assigned to a therapist."""
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")

    stmt = (
        select(TherapistSpecialty)
        .join(TherapistSpecialtyMap)
        .where(TherapistSpecialtyMap.therapist_id == therapist_id)
    )
    specialties = db.exec(stmt).all()

    return [
        SpecialtyResponse(
            id=s.id, name=s.name, description=s.description, is_active=s.is_active
        )
        for s in specialties
    ]


@router.post("/{therapist_id}/calendly-webhook/check", response_model=CalendlyWebhookCheckResponse)
def check_therapist_calendly_webhook(
    therapist_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """
    Admin-triggered Calendly webhook check for a therapist.

    Useful for operational diagnostics when onboarding spans multiple Calendly orgs.
    """
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")

    if not therapist.calendly_pat_encrypted:
        raise HTTPException(
            status_code=400,
            detail="Therapist does not have a stored Calendly PAT.",
        )

    if not settings.public_base_url:
        raise HTTPException(
            status_code=500,
            detail="PUBLIC_BASE_URL is not configured.",
        )

    calendly_pat = decrypt_string(therapist.calendly_pat_encrypted)
    endpoint_url = f"{settings.public_base_url.rstrip('/')}/api/v1/webhooks/calendly"

    try:
        status = check_webhook_registration(calendly_pat, endpoint_url)
    except CalendlyWebhookError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CalendlyWebhookCheckResponse(endpoint_url=endpoint_url, **status)
