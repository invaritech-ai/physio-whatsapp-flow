"""Business logic for therapist self-service onboarding."""

from typing import Any

from sqlmodel import Session, select

from app.core.encryption import decrypt_string, encrypt_string
from app.models import Therapist, TherapistEventType, TherapistSpecialty, TherapistSpecialtyMap
from app.services.calendly import get_event_types_with_pat, get_user_info_with_pat


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

    # Build response data
    data = {
        "valid": True,
        "user_uri": user_info["uri"],
        "name": user_info["name"],
        "email": user_info["email"],
        "event_types_found": len(event_types),
        "event_types": [
            {
                "calendly_event_type_uri": et["uri"],
                "duration_minutes": et["duration"],
                "name": et.get("name", ""),
                "scheduling_url": et.get("scheduling_url", ""),
            }
            for et in event_types
        ],
        "warnings": [],
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

    has_existing_mappings = bool(existing_event_types)

    # Create or update event types
    synced_event_types = []
    for et in event_types:
        duration = et["duration"]
        uri = et["uri"]
        scheduling_url = et.get("scheduling_url", "")
        is_active = et.get("active", True)

        existing_matches = [
            existing
            for existing in existing_event_types
            if existing.calendly_event_type_uri == uri
        ]

        if existing_matches:
            # Preserve mapped business durations; only refresh status/URL from Calendly.
            for existing in existing_matches:
                existing.scheduling_url = scheduling_url
                existing.is_active = is_active
                db.add(existing)
                synced_event_types.append(
                    {
                        "calendly_event_type_uri": uri,
                        "duration_minutes": existing.duration_minutes,
                        "scheduling_url": scheduling_url,
                    }
                )
        elif not has_existing_mappings:
            # Initial sync path: no explicit business-slot mappings yet, so seed rows from Calendly.
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
                    "calendly_event_type_uri": uri,
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
    new_specialties: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Update therapist's specialty assignments.

    Args:
        db: Database session
        therapist: Therapist model instance
        specialty_ids: List of existing specialty IDs to assign
        new_specialties: List of new specialty names to create and assign

    Returns:
        Tuple of (specialties, errors)
        - specialties: List of assigned specialty data
        - errors: List of error messages (empty if successful)
    """
    all_specialties: list[TherapistSpecialty] = []
    seen_specialty_ids: set[int] = set()

    def _add_specialty(specialty: TherapistSpecialty) -> None:
        if specialty.id is None:
            return
        if specialty.id in seen_specialty_ids:
            return
        seen_specialty_ids.add(specialty.id)
        all_specialties.append(specialty)

    # Validate existing specialty IDs
    deduped_specialty_ids = list(dict.fromkeys(specialty_ids))
    if deduped_specialty_ids:
        existing = db.exec(
            select(TherapistSpecialty).where(TherapistSpecialty.id.in_(deduped_specialty_ids))  # type: ignore
        ).all()

        if len(existing) != len(deduped_specialty_ids):
            found_ids = {s.id for s in existing}
            invalid_ids = set(deduped_specialty_ids) - found_ids
            return [], [f"Invalid specialty IDs: {', '.join(map(str, invalid_ids))}"]

        for specialty in existing:
            _add_specialty(specialty)

    # Create or find new specialties by name
    if new_specialties:
        for name in new_specialties:
            name = name.strip()
            if not name:
                continue
            # Check if specialty with this name already exists (case-insensitive)
            existing_by_name = db.exec(
                select(TherapistSpecialty).where(
                    TherapistSpecialty.name.ilike(name)  # type: ignore
                )
            ).first()
            if existing_by_name:
                # Reuse existing specialty (avoid duplicates)
                _add_specialty(existing_by_name)
            else:
                new_specialty = TherapistSpecialty(name=name)
                db.add(new_specialty)
                db.flush()  # Get the ID assigned
                _add_specialty(new_specialty)

    if not all_specialties:
        return [], ["At least one specialty is required"]

    # Apply a diff update to avoid unique-constraint clashes when keeping existing mappings.
    existing_mappings = db.exec(
        select(TherapistSpecialtyMap).where(
            TherapistSpecialtyMap.therapist_id == therapist.id
        )
    ).all()
    existing_specialty_ids = {m.specialty_id for m in existing_mappings}
    target_specialty_ids = [s.id for s in all_specialties if s.id is not None]
    target_specialty_id_set = set(target_specialty_ids)

    # Remove mappings no longer requested.
    for mapping in existing_mappings:
        if mapping.specialty_id not in target_specialty_id_set:
            db.delete(mapping)

    # Create only missing mappings.
    for specialty_id in target_specialty_ids:
        if specialty_id in existing_specialty_ids:
            continue
        db.add(
            TherapistSpecialtyMap(
                therapist_id=therapist.id,
                specialty_id=specialty_id,
            )
        )

    # Note: Do NOT commit here - let the route control the transaction

    # Return specialty info
    specialty_data = [{"id": s.id, "name": s.name} for s in all_specialties]
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
    3. Verify Calendly PAT and event types can be read
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
    if not therapist.license_number or not therapist.license_number.strip():
        return False, {}, ["license_number_required"]

    # Step 1: Validate Calendly PAT
    valid, validation_data, errors = validate_calendly_pat(calendly_pat)
    if not valid:
        return False, {}, errors

    # Step 2: Check not already onboarded
    if therapist.calendly_user_uri:
        return False, {}, ["Therapist already has Calendly URI set"]

    # Step 3: Update calendly_user_uri and store encrypted PAT
    therapist.calendly_user_uri = validation_data["user_uri"]
    therapist.calendly_pat_encrypted = encrypt_string(calendly_pat)
    db.add(therapist)

    # Step 4: Sync event types
    event_types, sync_errors = sync_event_types(db, therapist, calendly_pat)
    if sync_errors:
        return False, {}, sync_errors

    # Step 5: Assign specialties
    specialties, specialty_errors = update_therapist_specialties(db, therapist, specialty_ids)
    if specialty_errors:
        return False, {}, specialty_errors

    # Step 6: Activate therapist
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
