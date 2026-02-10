"""Therapist self-service onboarding endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.auth import get_current_therapist_allow_inactive
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
    UpdateSpecialtiesRequest,
    UpdateSpecialtiesResponse,
    SaveCalendlyRequest,
    SaveCalendlyResponse,
    TherapistProfileResponse,
    EventTypeInfo,
    EventTypeDetail,
    SpecialtyInfo,
)
from app.services.therapist_onboarding import (
    validate_calendly_pat,
    sync_event_types,
    update_therapist_specialties,
    complete_therapist_onboarding,
)

router = APIRouter(prefix="/therapist", tags=["Therapist - Onboarding"])


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
    3. Verify required event types (30/45/60 min) exist
    4. Update therapist.calendly_user_uri
    5. Sync event types to database
    6. Assign specialties
    7. Activate therapist

    Raises:
        400: Invalid PAT, missing event types, invalid specialty IDs, or already onboarded
    """
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

    # Determine onboarding status
    has_calendly_uri = therapist.calendly_user_uri is not None
    has_event_types = len(event_types) > 0
    has_specialties = len(specialty_mappings) > 0
    is_onboarded = has_calendly_uri and has_event_types and has_specialties and therapist.is_active

    # Build missing steps list
    missing_steps = []
    if not has_calendly_uri:
        missing_steps.append("calendly_setup")
    if not has_event_types:
        missing_steps.append("event_types")
    if not has_specialties:
        missing_steps.append("specialties")
    if not therapist.is_active:
        missing_steps.append("activation")

    return OnboardingStatusResponse(
        is_onboarded=is_onboarded,
        has_calendly_uri=has_calendly_uri,
        has_event_types=has_event_types,
        event_types_count=len(event_types),
        has_specialties=has_specialties,
        specialties_count=len(specialty_mappings),
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
    Includes warnings if required event types (30/45/60 min) are missing.

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

    # Also update user display_name
    user = db.get(User, therapist.user_id)
    if user:
        user.display_name = data.display_name

    db.add(therapist)
    if user:
        db.add(user)
    db.commit()
    db.refresh(therapist)

    return UpdateProfileResponse(display_name=therapist.display_name)


@router.post("/onboarding/calendly", response_model=SaveCalendlyResponse)
def save_calendly(
    data: SaveCalendlyRequest,
    therapist: Therapist = Depends(get_current_therapist_allow_inactive),
    db: Session = Depends(get_session),
):
    """
    Save Calendly PAT and activate therapist account.

    Step 3 of onboarding: Connect Calendly account, sync event types, and activate.

    This endpoint:
    1. Validates and encrypts the Calendly PAT
    2. Syncs event types from Calendly
    3. Activates the therapist account
    """
    from app.services.therapist_onboarding import validate_calendly_pat, sync_event_types
    from app.core.encryption import encrypt_string

    # Validate PAT
    success, validation_data, errors = validate_calendly_pat(data.calendly_pat)
    if not success:
        raise HTTPException(status_code=400, detail=errors[0] if errors else "Invalid Calendly PAT")

    # Encrypt and save PAT
    encrypted_pat = encrypt_string(data.calendly_pat)
    therapist.calendly_pat_encrypted = encrypted_pat
    therapist.calendly_user_uri = validation_data["user_uri"]

    # Sync event types
    _, sync_errors = sync_event_types(db, therapist, data.calendly_pat)
    if sync_errors:
        raise HTTPException(status_code=400, detail=sync_errors[0])

    # Activate therapist
    therapist.is_active = True

    db.add(therapist)
    db.commit()
    db.refresh(therapist)

    # Get event types for response
    event_type_objs = db.exec(
        select(TherapistEventType).where(TherapistEventType.therapist_id == therapist.id)
    ).all()

    # calendly_user_uri should always be set after validation
    if not therapist.calendly_user_uri:
        raise HTTPException(status_code=500, detail="Failed to set Calendly user URI")

    return SaveCalendlyResponse(
        calendly_user_uri=therapist.calendly_user_uri,
        event_types_synced=len(event_type_objs),
        event_types=[
            EventTypeInfo(
                duration_minutes=et.duration_minutes,
                name=None,
                scheduling_url=et.scheduling_url,
            )
            for et in event_type_objs
        ],
        is_active=therapist.is_active,
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
            duration_minutes=et.duration_minutes,
            scheduling_url=et.scheduling_url,
            is_active=et.is_active,
        )
        for et in event_types
    ]

    return TherapistProfileResponse(
        id=therapist.id,
        user_id=therapist.user_id,
        display_name=therapist.display_name,
        email=user.email if user else None,
        is_active=therapist.is_active,
        calendly_user_uri=therapist.calendly_user_uri,
        specialties=specialty_info,
        event_types=event_type_info,
        created_at=therapist.created_at,
    )
