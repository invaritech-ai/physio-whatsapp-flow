"""Therapist self-service onboarding endpoints."""

import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.auth import get_current_therapist_allow_inactive
from app.core.config import settings
from app.core.encryption import decrypt_string, encrypt_string
from app.db.session import get_session
from app.models import Therapist, TherapistEventType, TherapistSpecialty, TherapistSpecialtyMap, User
from app.api.v1.schemas.therapist_onboarding import (
    CompleteOnboardingRequest,
    CompleteOnboardingResponse,
    OnboardingStatusResponse,
    ValidateCalendlyRequest,
    ValidateCalendlyResponse,
    EventTypeSyncResponse,
    UpdateProfileRequest,
    UpdateProfileResponse,
    UpdatePreferredTimezoneRequest,
    UpdatePreferredTimezoneResponse,
    UpdateSpecialtiesRequest,
    UpdateSpecialtiesResponse,
    SaveCalendlyRequest,
    SaveCalendlyResponse,
    SlotMappingInfo,
    TherapistProfileResponse,
    EventTypeInfo,
    EventTypeDetail,
    SpecialtyInfo,
    CalendlyWebhookActionRequest,
    CalendlyWebhookCheckResponse,
    CalendlyWebhookRegisterResponse,
)
from app.services.calendly_webhooks import (
    CalendlyWebhookError,
    check_webhook_registration,
    register_webhook_if_needed,
)
from app.services.therapist_onboarding import (
    validate_calendly_pat,
    sync_event_types,
    update_therapist_specialties,
    complete_therapist_onboarding,
)
from app.services.license_numbers import is_valid_license_number, normalize_license_number

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/therapist", tags=["Therapist - Onboarding"])


def _resolve_calendly_pat(therapist: Therapist, explicit_pat: str | None = None) -> str:
    if explicit_pat:
        return explicit_pat
    if therapist.calendly_pat_encrypted:
        return decrypt_string(therapist.calendly_pat_encrypted)
    raise HTTPException(
        status_code=400,
        detail="Calendly PAT not configured. Connect Calendly first.",
    )


def _calendly_webhook_endpoint() -> str:
    if not settings.public_base_url:
        raise HTTPException(
            status_code=500,
            detail="PUBLIC_BASE_URL is not configured.",
        )
    return f"{settings.public_base_url.rstrip('/')}/api/v1/webhooks/calendly"


def _normalize_and_validate_license_number(value: str | None) -> str | None:
    normalized = normalize_license_number(value)
    if normalized is None:
        return None
    if not is_valid_license_number(normalized):
        raise HTTPException(status_code=400, detail="invalid_license_number")
    return normalized


def _normalize_and_validate_timezone(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="invalid_preferred_timezone")
    try:
        return ZoneInfo(normalized).key
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=400, detail="invalid_preferred_timezone") from exc


def _ensure_unique_license_number(
    db: Session,
    *,
    therapist_id: int | None,
    license_number: str | None,
) -> None:
    if license_number is None:
        return
    existing = db.exec(
        select(Therapist).where(Therapist.license_number == license_number)
    ).first()
    if existing and existing.id != therapist_id:
        raise HTTPException(status_code=400, detail="license_number_already_exists")


def _require_license_number(therapist: Therapist) -> None:
    if not therapist.license_number or not therapist.license_number.strip():
        raise HTTPException(status_code=400, detail="license_number_required")


@router.post("/onboarding/complete", response_model=CompleteOnboardingResponse, status_code=201)
def complete_onboarding(
    data: CompleteOnboardingRequest,
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
    db: Session = Depends(get_session),
):
    """
    Complete therapist onboarding in one atomic transaction.

    Steps:
    1. Validate Calendly PAT
    2. Check therapist not already onboarded
    3. Update therapist.calendly_user_uri
    4. Sync event types to database
    5. Assign specialties
    6. Activate therapist

    Raises:
        400: Invalid PAT, missing event types, invalid specialty IDs, or already onboarded
    """
    _require_license_number(therapist)
    try:
        success, response_data, errors = complete_therapist_onboarding(
            db, therapist, data.calendly_pat, data.specialty_ids
        )

        if not success:
            error_message = errors[0] if errors else "Onboarding failed"
            raise HTTPException(status_code=400, detail=error_message)

        # Commit transaction
        db.commit()
        db.refresh(therapist)

        return CompleteOnboardingResponse(**response_data)

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Onboarding failed: {str(e)}")


@router.get("/onboarding/status", response_model=OnboardingStatusResponse)
def get_onboarding_status(
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
    db: Session = Depends(get_session),
):
    """
    Check onboarding completion status.

    Returns whether therapist has completed all onboarding steps:
    - Calendly URI set
    - Event types synced
    - Specialties assigned
    - Account activated
    """
    # Check event types
    event_types = db.exec(
        select(TherapistEventType)
        .where(TherapistEventType.therapist_id == therapist.id)
        .where(TherapistEventType.is_active == True)  # noqa: E712
    ).all()

    # Check specialties
    specialty_mappings = db.exec(
        select(TherapistSpecialtyMap).where(
            TherapistSpecialtyMap.therapist_id == therapist.id
        )
    ).all()

    # Determine step states
    has_profile_name = therapist.display_name is not None and therapist.display_name != ""
    has_license_number = (
        therapist.license_number is not None and therapist.license_number.strip() != ""
    )
    has_calendly_uri = therapist.calendly_user_uri is not None
    has_event_types = len(event_types) > 0
    has_specialties = len(specialty_mappings) > 0

    # Slot mapping is complete once the therapist has at least one active mapped event type.
    has_slot_mapping = has_event_types

    is_onboarded = (
        has_profile_name and has_license_number and has_specialties and has_calendly_uri
        and has_slot_mapping and therapist.is_active
    )

    # Build missing steps list
    missing_steps = []
    if not has_profile_name:
        missing_steps.append("profile_name")
    if not has_license_number:
        missing_steps.append("license_number")
    if not has_specialties:
        missing_steps.append("specialties")
    if not has_calendly_uri:
        missing_steps.append("calendly_setup")
    if not has_event_types:
        missing_steps.append("event_types")
    if not has_slot_mapping:
        missing_steps.append("slot_mapping")
    if not therapist.is_active:
        missing_steps.append("activation")

    return OnboardingStatusResponse(
        is_onboarded=is_onboarded,
        has_profile_name=has_profile_name,
        has_license_number=has_license_number,
        has_specialties=has_specialties,
        specialties_count=len(specialty_mappings),
        has_calendly_uri=has_calendly_uri,
        has_slot_mapping=has_slot_mapping,
        has_event_types=has_event_types,
        event_types_count=len(event_types),
        is_active=therapist.is_active,
        missing_steps=missing_steps,
    )


@router.post("/onboarding/validate-calendly", response_model=ValidateCalendlyResponse)
def validate_calendly_token(
    data: ValidateCalendlyRequest,
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
):
    """
    Validate Calendly PAT and preview what will be synced (dry-run).

    Returns user info and event types found in Calendly.

    Raises:
        400: Invalid Calendly token
    """
    valid, validation_data, errors = validate_calendly_pat(data.calendly_pat)

    if not valid:
        error_message = errors[0] if errors else "Invalid Calendly token"
        raise HTTPException(status_code=400, detail=error_message)

    # Convert event types to schema format
    event_types = [EventTypeInfo(**et) for et in validation_data["event_types"]]

    return ValidateCalendlyResponse(
        valid=validation_data["valid"],
        user_uri=validation_data["user_uri"],
        name=validation_data["name"],
        email=validation_data["email"],
        event_types_found=validation_data["event_types_found"],
        event_types=event_types,
        warnings=validation_data["warnings"],
    )


@router.post("/sync-event-types", response_model=EventTypeSyncResponse)
def resync_event_types(
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
    db: Session = Depends(get_session),
):
    """
    Re-sync event types from Calendly.

    Uses existing calendly_user_uri (therapist must already be onboarded).
    Useful when therapist adds/updates event types in Calendly.

    Raises:
        400: Therapist does not have Calendly URI set or no event types found
    """
    if not therapist.calendly_user_uri:
        raise HTTPException(
            status_code=400,
            detail="Therapist does not have Calendly URI set. Complete onboarding first.",
        )

    try:
        event_types, errors = sync_event_types(db, therapist, calendly_pat=None)

        if errors:
            error_message = errors[0] if errors else "Event type sync failed"
            raise HTTPException(status_code=400, detail=error_message)

        # Commit transaction
        db.commit()

        # Convert to schema format
        event_types_info = [EventTypeInfo(**et) for et in event_types]

        return EventTypeSyncResponse(
            event_types_synced=len(event_types_info),
            event_types=event_types_info,
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Event type sync failed: {str(e)}")


@router.patch("/specialties", response_model=UpdateSpecialtiesResponse)
def update_specialties(
    data: UpdateSpecialtiesRequest,
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
    db: Session = Depends(get_session),
):
    """
    Update therapist specialties.

    Replaces all existing specialty assignments with the new list.

    Raises:
        400: Invalid specialty IDs
    """
    try:
        specialties, errors = update_therapist_specialties(
            db, therapist, data.specialty_ids, data.new_specialties
        )

        if errors:
            error_message = errors[0] if errors else "Specialty update failed"
            raise HTTPException(status_code=400, detail=error_message)

        # Commit transaction
        db.commit()

        # Convert to schema format
        specialty_info = [SpecialtyInfo(**s) for s in specialties]

        return UpdateSpecialtiesResponse(specialties=specialty_info)

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Specialty update failed: {str(e)}")


@router.get("/specialties/catalog", response_model=list[SpecialtyInfo])
def list_specialties_catalog(
    active_only: bool = True,
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
    db: Session = Depends(get_session),
):
    """
    List available specialties for autocomplete/suggestions.

    Used during onboarding Step 2 to show existing specialty options.
    """
    stmt = select(TherapistSpecialty)
    if active_only:
        stmt = stmt.where(TherapistSpecialty.is_active == True)  # noqa: E712
    stmt = stmt.order_by(TherapistSpecialty.name)

    specialties = db.exec(stmt).all()
    return [SpecialtyInfo(id=s.id, name=s.name) for s in specialties]


@router.patch("/onboarding/profile", response_model=UpdateProfileResponse)
def update_profile(
    data: UpdateProfileRequest,
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
    db: Session = Depends(get_session),
):
    """
    Update therapist profile (display name).

    Step 1 of onboarding: Save therapist's display name.
    """
    # Update therapist display_name
    therapist.display_name = data.display_name
    if "license_number" in data.model_fields_set:
        normalized_license = _normalize_and_validate_license_number(data.license_number)
        _ensure_unique_license_number(
            db,
            therapist_id=therapist.id,
            license_number=normalized_license,
        )
        therapist.license_number = normalized_license

    # Also update user display_name
    user = db.get(User, therapist.user_id)
    if user:
        user.display_name = data.display_name

    db.add(therapist)
    if user:
        db.add(user)
    db.commit()
    db.refresh(therapist)

    return UpdateProfileResponse(
        display_name=therapist.display_name,
        license_number=therapist.license_number,
    )


@router.post("/onboarding/calendly", response_model=SaveCalendlyResponse)
def save_calendly(
    data: SaveCalendlyRequest,
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
    db: Session = Depends(get_session),
):
    """
    Save Calendly PAT with explicit slot mapping and activate therapist account.

    Step 3 of onboarding: Connect Calendly account, persist slot mapping, and activate.

    Request body:
    - calendly_pat: Personal Access Token
    - slot_mapping: {"30": "<event_type_uri>", "45": "<uri>"}

    Server validates each URI belongs to the therapist's Calendly account,
    persists only the mapped event types, and activates the account.
    """
    _require_license_number(therapist)
    from app.core.encryption import encrypt_string

    # Validate PAT
    success, validation_data, errors = validate_calendly_pat(data.calendly_pat)
    if not success:
        raise HTTPException(status_code=400, detail=errors[0] if errors else "Invalid Calendly PAT")

    # Build lookup of validated event types by URI
    valid_event_types = {
        et["calendly_event_type_uri"]: et for et in validation_data["event_types"]
    }

    # Validate each slot mapping URI exists in the validated event types
    for duration_str, uri in data.slot_mapping.items():
        if uri not in valid_event_types:
            raise HTTPException(
                status_code=400,
                detail=f"Event type URI not found in Calendly account: {uri}",
            )

    # Encrypt and save PAT
    therapist.calendly_pat_encrypted = encrypt_string(data.calendly_pat)
    therapist.calendly_user_uri = validation_data["user_uri"]

    # Check if any of these event type URIs are already mapped to another therapist
    uris_to_insert = list(data.slot_mapping.values())
    conflicts = db.exec(
        select(TherapistEventType).where(
            TherapistEventType.calendly_event_type_uri.in_(uris_to_insert),  # type: ignore
            TherapistEventType.therapist_id != therapist.id,
        )
    ).all()
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail="These Calendly event types are already linked to another therapist. "
            "Each event type can only be mapped to one therapist.",
        )

    # Clear existing event types for this therapist
    existing_event_types = db.exec(
        select(TherapistEventType).where(TherapistEventType.therapist_id == therapist.id)
    ).all()
    for et in existing_event_types:
        db.delete(et)
    db.flush()

    # Persist only the mapped slot event types
    slot_mapping_response = []
    for duration_str, uri in data.slot_mapping.items():
        et_data = valid_event_types[uri]
        event_type = TherapistEventType(
            therapist_id=therapist.id,
            calendly_event_type_uri=uri,
            duration_minutes=int(duration_str),
            scheduling_url=et_data["scheduling_url"],
            is_active=True,
        )
        db.add(event_type)
        slot_mapping_response.append(SlotMappingInfo(
            duration_minutes=int(duration_str),
            calendly_event_type_uri=uri,
            scheduling_url=et_data["scheduling_url"],
        ))

    # Activate therapist
    therapist.is_active = True
    db.add(therapist)
    db.commit()
    db.refresh(therapist)

    return SaveCalendlyResponse(
        calendly_user_uri=therapist.calendly_user_uri,
        slot_mapping=sorted(slot_mapping_response, key=lambda s: s.duration_minutes),
        is_active=therapist.is_active,
    )


@router.post("/onboarding/calendly-webhook/check", response_model=CalendlyWebhookCheckResponse)
def check_calendly_webhook(
    data: CalendlyWebhookActionRequest,
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
):
    """
    Check whether Calendly webhook registration is needed for this therapist.

    Uses stored encrypted PAT by default, or request PAT override if provided.
    """
    calendly_pat = _resolve_calendly_pat(therapist, data.calendly_pat)
    endpoint_url = _calendly_webhook_endpoint()
    try:
        status = check_webhook_registration(calendly_pat, endpoint_url)
    except CalendlyWebhookError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if status.get("has_matching_webhook") and not therapist.calendly_webhook_signing_key_encrypted:
        warnings = list(status.get("warnings", []))
        warnings.append(
            "Webhook is active but no signing key is stored yet. Re-register webhook to sync signing key."
        )
        status["warnings"] = warnings

    return CalendlyWebhookCheckResponse(
        endpoint_url=endpoint_url,
        **status,
    )


@router.post("/onboarding/calendly-webhook/register", response_model=CalendlyWebhookRegisterResponse)
def register_calendly_webhook(
    data: CalendlyWebhookActionRequest,
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
    db: Session = Depends(get_session),
):
    """
    Register Calendly webhook for this therapist if missing (idempotent).

    Uses user-scope registration so therapists from different Calendly orgs can
    self-provision their own webhook subscription.
    """
    logger.debug(
        "[DEBUG-ONBOARD] register_calendly_webhook called for therapist_id=%s, calendly_user_uri=%s",
        therapist.id, therapist.calendly_user_uri,
    )
    logger.debug(
        "[DEBUG-ONBOARD] therapist has stored signing key: %s",
        therapist.calendly_webhook_signing_key_encrypted is not None,
    )
    calendly_pat = _resolve_calendly_pat(therapist, data.calendly_pat)
    endpoint_url = _calendly_webhook_endpoint()
    logger.debug("[DEBUG-ONBOARD] endpoint_url=%s", endpoint_url)
    try:
        result = register_webhook_if_needed(calendly_pat, endpoint_url)
    except CalendlyWebhookError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    warnings = list(result.get("warnings", []))
    signing_key = result.get("signing_key")
    logger.debug(
        "[DEBUG-ONBOARD] register result: created=%s, signing_key_returned=%s, has_matching=%s",
        result.get("created"), signing_key is not None, result.get("has_matching_webhook"),
    )

    # Persist Calendly signing key so webhook verification no longer depends on env config.
    if signing_key:
        therapist.calendly_webhook_signing_key_encrypted = encrypt_string(signing_key)
        db.add(therapist)
        db.commit()
        db.refresh(therapist)
        logger.debug("[DEBUG-ONBOARD] signing key persisted for therapist_id=%s (key=%s…)", therapist.id, signing_key[:8])
    elif result.get("has_matching_webhook") and not therapist.calendly_webhook_signing_key_encrypted:
        logger.debug("[DEBUG-ONBOARD] webhook exists but NO signing key stored — orphaned webhook")
        warnings.append(
            "Webhook exists but signing key was not returned by Calendly. Recreate webhook to sync signing key."
        )

    result["warnings"] = warnings
    # Do not expose raw signing key back to clients after registration.
    result["signing_key"] = None

    return CalendlyWebhookRegisterResponse(
        endpoint_url=endpoint_url,
        **result,
    )


@router.patch("/me/timezone", response_model=UpdatePreferredTimezoneResponse)
def update_preferred_timezone(
    data: UpdatePreferredTimezoneRequest,
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
    db: Session = Depends(get_session),
):
    """Update therapist preferred timezone with strict IANA validation."""
    therapist.preferred_timezone = _normalize_and_validate_timezone(
        data.preferred_timezone
    )
    db.add(therapist)
    db.commit()
    db.refresh(therapist)
    return UpdatePreferredTimezoneResponse(
        preferred_timezone=therapist.preferred_timezone
    )


@router.get("/me", response_model=TherapistProfileResponse)
def get_therapist_profile(
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
    db: Session = Depends(get_session),
):
    """
    Get current therapist's full profile.

    Returns therapist details including:
    - Basic info (ID, name, email, status)
    - Calendly user URI
    - Assigned specialties
    - Event types
    """
    # Get user for email
    user = db.get(User, therapist.user_id)

    # Get specialties
    stmt = (
        select(TherapistSpecialty)
        .join(TherapistSpecialtyMap)
        .where(TherapistSpecialtyMap.therapist_id == therapist.id)
    )
    specialties = db.exec(stmt).all()

    # Get event types
    event_types = db.exec(
        select(TherapistEventType).where(
            TherapistEventType.therapist_id == therapist.id
        )
    ).all()

    # Convert to schema format
    specialty_info = [
        SpecialtyInfo(id=s.id, name=s.name) for s in specialties
    ]

    event_type_info = [
        EventTypeDetail(
            id=et.id,
            calendly_event_type_uri=et.calendly_event_type_uri,
            duration_minutes=et.duration_minutes,
            scheduling_url=et.scheduling_url,
            is_active=et.is_active,
        )
        for et in event_types
    ]

    # Build slot mapping from active event types
    slot_mapping = [
        SlotMappingInfo(
            duration_minutes=et.duration_minutes,
            calendly_event_type_uri=et.calendly_event_type_uri,
            scheduling_url=et.scheduling_url,
        )
        for et in event_types
        if et.is_active
    ]

    return TherapistProfileResponse(
        id=therapist.id,
        user_id=therapist.user_id,
        display_name=therapist.display_name,
        license_number=therapist.license_number,
        preferred_timezone=therapist.preferred_timezone,
        email=user.email if user else None,
        is_active=therapist.is_active,
        calendly_user_uri=therapist.calendly_user_uri,
        specialties=specialty_info,
        event_types=event_type_info,
        slot_mapping=sorted(slot_mapping, key=lambda s: s.duration_minutes),
        created_at=therapist.created_at,
    )
