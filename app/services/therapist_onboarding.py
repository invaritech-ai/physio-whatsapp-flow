"""Business logic for therapist self-service onboarding."""

from typing import Any

from sqlmodel import Session, select

from app.core.encryption import decrypt_string, encrypt_string
from app.models import Therapist, TherapistEventType, TherapistSpecialty, TherapistSpecialtyMap
from app.services.calendly import get_event_types_with_pat, get_user_info_with_pat


# Required event type durations for onboarding
REQUIRED_DURATIONS = {30, 45, 60}


def validate_calendly_pat(calendly_pat: str) -> tuple[bool, dict[str, Any], list[str]]:
    """Validate Calendly PAT and preview what will be synced.

    Args:
        calendly_pat: Therapist's Calendly Personal Access Token

    Returns:
        Tuple of (success, data, errors)
        - success: True if PAT is valid
        - data: Dictionary with user info and event types
        - errors: List of error messages (empty if valid)
    """
    # Fetch user info
    user_info = get_user_info_with_pat(calendly_pat)
    if not user_info:
        return False, {}, ["Invalid Calendly token"]

    # Fetch event types
    event_types = get_event_types_with_pat(user_info["uri"], calendly_pat)

    # Check for required durations
    found_durations = {et["duration"] for et in event_types}
    missing_durations = REQUIRED_DURATIONS - found_durations

    # Build warnings for missing durations
    warnings = []
    for duration in sorted(missing_durations):
        warnings.append(f"Missing {duration}-minute event type")

    # Build response data
    data = {
        "valid": True,
        "user_uri": user_info["uri"],
        "name": user_info["name"],
        "email": user_info["email"],
        "event_types_found": len(event_types),
        "event_types": [
            {
                "duration_minutes": et["duration"],
                "name": et.get("name", ""),
                "scheduling_url": et.get("scheduling_url", ""),
            }
            for et in event_types
        ],
        "warnings": warnings,
    }

    return True, data, []


def sync_event_types(
    db: Session,
    therapist: Therapist,
    calendly_pat: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Sync event types from Calendly for a therapist.

    Args:
        db: Database session
        therapist: Therapist model instance
        calendly_pat: Optional PAT (if None, must use existing calendly_user_uri with org token)

    Returns:
        Tuple of (event_types, errors)
        - event_types: List of synced event type data
        - errors: List of error messages (empty if successful)
    """
    if not therapist.calendly_user_uri:
        return [], ["Therapist does not have Calendly user URI set"]

    # Fetch event types
    if calendly_pat:
        # Use provided PAT (during onboarding)
        event_types = get_event_types_with_pat(therapist.calendly_user_uri, calendly_pat)
    elif therapist.calendly_pat_encrypted:
        # Use stored encrypted PAT (for re-sync after onboarding)
        decrypted_pat = decrypt_string(therapist.calendly_pat_encrypted)
        event_types = get_event_types_with_pat(therapist.calendly_user_uri, decrypted_pat)
    else:
        # Fallback to org-level token (if no PAT stored)
        from app.services.calendly import get_event_types

        event_types = get_event_types(therapist.calendly_user_uri)

    if not event_types:
        return [], ["No event types found in Calendly"]

    # Deactivate existing event types (we'll reactivate if they still exist)
    existing_event_types = db.exec(
        select(TherapistEventType).where(TherapistEventType.therapist_id == therapist.id)
    ).all()
    for et in existing_event_types:
        et.is_active = False
        db.add(et)

    # Create or update event types
    synced_event_types = []
    for et in event_types:
        duration = et["duration"]
        uri = et["uri"]
        scheduling_url = et.get("scheduling_url", "")
        is_active = et.get("active", True)

        # Check if already exists
        stmt = select(TherapistEventType).where(
            TherapistEventType.calendly_event_type_uri == uri
        )
        existing = db.exec(stmt).first()

        if existing:
            # Update existing
            existing.duration_minutes = duration
            existing.scheduling_url = scheduling_url
            existing.is_active = is_active
            db.add(existing)
        else:
            # Create new
            new_event_type = TherapistEventType(
                therapist_id=therapist.id,
                calendly_event_type_uri=uri,
                duration_minutes=duration,
                scheduling_url=scheduling_url,
                is_active=is_active,
            )
            db.add(new_event_type)

        synced_event_types.append(
            {
                "duration_minutes": duration,
                "scheduling_url": scheduling_url,
            }
        )

    # Note: Do NOT commit here - let the route control the transaction
    return synced_event_types, []


def update_therapist_specialties(
    db: Session,
    therapist: Therapist,
    specialty_ids: list[int],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Update therapist's specialty assignments.

    Args:
        db: Database session
        therapist: Therapist model instance
        specialty_ids: List of specialty IDs to assign

    Returns:
        Tuple of (specialties, errors)
        - specialties: List of assigned specialty data
        - errors: List of error messages (empty if successful)
    """
    # Validate all specialty IDs exist
    specialties = db.exec(
        select(TherapistSpecialty).where(TherapistSpecialty.id.in_(specialty_ids))  # type: ignore
    ).all()

    if len(specialties) != len(specialty_ids):
        found_ids = {s.id for s in specialties}
        invalid_ids = set(specialty_ids) - found_ids
        return [], [f"Invalid specialty IDs: {', '.join(map(str, invalid_ids))}"]

    # Delete existing specialty mappings
    existing_mappings = db.exec(
        select(TherapistSpecialtyMap).where(
            TherapistSpecialtyMap.therapist_id == therapist.id
        )
    ).all()
    for mapping in existing_mappings:
        db.delete(mapping)

    # Create new mappings
    for specialty_id in specialty_ids:
        mapping = TherapistSpecialtyMap(
            therapist_id=therapist.id,
            specialty_id=specialty_id,
        )
        db.add(mapping)

    # Note: Do NOT commit here - let the route control the transaction

    # Return specialty info
    specialty_data = [{"id": s.id, "name": s.name} for s in specialties]
    return specialty_data, []


def complete_therapist_onboarding(
    db: Session,
    therapist: Therapist,
    calendly_pat: str,
    specialty_ids: list[int],
) -> tuple[bool, dict[str, Any], list[str]]:
    """Complete therapist onboarding in one atomic transaction.

    Steps:
    1. Validate Calendly PAT
    2. Check therapist not already onboarded
    3. Verify required event types exist
    4. Update therapist.calendly_user_uri
    5. Sync event types
    6. Assign specialties
    7. Activate therapist

    Args:
        db: Database session
        therapist: Therapist model instance
        calendly_pat: Therapist's Calendly Personal Access Token
        specialty_ids: List of specialty IDs to assign

    Returns:
        Tuple of (success, data, errors)
        - success: True if onboarding completed successfully
        - data: Dictionary with therapist profile data
        - errors: List of error messages (empty if successful)
    """
    # Step 1: Validate Calendly PAT
    valid, validation_data, errors = validate_calendly_pat(calendly_pat)
    if not valid:
        return False, {}, errors

    # Step 2: Check not already onboarded
    if therapist.calendly_user_uri:
        return False, {}, ["Therapist already has Calendly URI set"]

    # Step 3: Verify required event types exist
    if validation_data["warnings"]:
        # Missing required durations
        missing = [w.replace("Missing ", "").replace(" event type", "") for w in validation_data["warnings"]]
        return False, {}, [f"Missing required event types: {', '.join(missing)}"]

    # Step 4: Update calendly_user_uri and store encrypted PAT
    therapist.calendly_user_uri = validation_data["user_uri"]
    therapist.calendly_pat_encrypted = encrypt_string(calendly_pat)
    db.add(therapist)

    # Step 5: Sync event types
    event_types, sync_errors = sync_event_types(db, therapist, calendly_pat)
    if sync_errors:
        return False, {}, sync_errors

    # Step 6: Assign specialties
    specialties, specialty_errors = update_therapist_specialties(db, therapist, specialty_ids)
    if specialty_errors:
        return False, {}, specialty_errors

    # Step 7: Activate therapist
    therapist.is_active = True
    db.add(therapist)

    # Note: Do NOT commit here - let the route control the transaction

    # Build success response
    data = {
        "therapist_id": therapist.id,
        "display_name": therapist.display_name,
        "calendly_user_uri": therapist.calendly_user_uri,
        "is_active": therapist.is_active,
        "specialties": specialties,
        "event_types_synced": len(event_types),
        "event_types": event_types,
    }

    return True, data, []
