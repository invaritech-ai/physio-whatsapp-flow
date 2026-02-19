"""Admin endpoints for managing therapists."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.auth import get_current_admin
from app.core.config import settings
from app.core.encryption import decrypt_string
from app.db.session import get_session
from app.models import Therapist, TherapistSpecialty, TherapistSpecialtyMap, User
from app.api.v1.schemas.therapist_onboarding import CalendlyWebhookCheckResponse
from app.api.v1.schemas.therapist import (
    TherapistCreate,
    TherapistUpdate,
    TherapistResponse,
    TherapistListResponse,
    SpecialtyAssignment,
)
from app.api.v1.schemas.specialty import SpecialtyResponse
from app.services.calendly_webhooks import CalendlyWebhookError, check_webhook_registration
from app.services.license_numbers import is_valid_license_number, normalize_license_number

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

    # Create User record
    user = User(
        neon_auth_sub=data.neon_auth_sub,
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
        is_active=True,
    )
    db.add(therapist)
    db.commit()
    db.refresh(therapist)

    # Return with empty specialties list
    return TherapistResponse(
        id=therapist.id,
        user_id=therapist.user_id,
        display_name=therapist.display_name,
        license_number=therapist.license_number,
        is_active=therapist.is_active,
        calendly_user_uri=therapist.calendly_user_uri,
        specialties=[],
        created_at=therapist.created_at,
    )


@router.get("", response_model=list[TherapistListResponse])
def list_therapists(admin: User = Depends(get_current_admin), db: Session = Depends(get_session)):
    """List all therapists with basic info."""
    stmt = select(Therapist, User).join(User).order_by(Therapist.created_at.desc())
    results = db.exec(stmt).all()

    therapists = []
    for therapist, user in results:
        # Count specialties
        specialty_count = len(
            db.exec(
                select(TherapistSpecialtyMap).where(
                    TherapistSpecialtyMap.therapist_id == therapist.id
                )
            ).all()
        )

        therapists.append(
            TherapistListResponse(
                id=therapist.id,
                display_name=therapist.display_name,
                license_number=therapist.license_number,
                is_active=therapist.is_active,
                email=user.email,
                specialty_count=specialty_count,
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
        calendly_user_uri=therapist.calendly_user_uri,
        specialties=[
            SpecialtyResponse(
                id=s.id, name=s.name, description=s.description, is_active=s.is_active
            )
            for s in specialties
        ],
        created_at=therapist.created_at,
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
