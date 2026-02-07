"""Admin endpoints for managing specialties."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import TherapistSpecialty
from app.api.v1.schemas.specialty import (
    SpecialtyCreate,
    SpecialtyUpdate,
    SpecialtyResponse,
)

router = APIRouter(prefix="/admin/specialties", tags=["Admin - Specialties"])


@router.post("", response_model=SpecialtyResponse, status_code=201)
def create_specialty(data: SpecialtyCreate, db: Session = Depends(get_session)):
    """Create a new specialty."""
    # Check if name already exists
    existing = db.exec(
        select(TherapistSpecialty).where(TherapistSpecialty.name == data.name)
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Specialty name already exists")

    specialty = TherapistSpecialty(
        name=data.name, description=data.description, is_active=True
    )

    db.add(specialty)
    db.commit()
    db.refresh(specialty)

    return SpecialtyResponse(
        id=specialty.id,
        name=specialty.name,
        description=specialty.description,
        is_active=specialty.is_active,
    )


@router.get("", response_model=list[SpecialtyResponse])
def list_specialties(active_only: bool = False, db: Session = Depends(get_session)):
    """List all specialties (optionally filter to active only)."""
    stmt = select(TherapistSpecialty).order_by(TherapistSpecialty.name)

    if active_only:
        stmt = stmt.where(TherapistSpecialty.is_active == True)  # noqa: E712

    specialties = db.exec(stmt).all()

    return [
        SpecialtyResponse(
            id=s.id, name=s.name, description=s.description, is_active=s.is_active
        )
        for s in specialties
    ]


@router.get("/{specialty_id}", response_model=SpecialtyResponse)
def get_specialty(specialty_id: int, db: Session = Depends(get_session)):
    """Get specialty detail."""
    specialty = db.get(TherapistSpecialty, specialty_id)
    if not specialty:
        raise HTTPException(status_code=404, detail="Specialty not found")

    return SpecialtyResponse(
        id=specialty.id,
        name=specialty.name,
        description=specialty.description,
        is_active=specialty.is_active,
    )


@router.patch("/{specialty_id}", response_model=SpecialtyResponse)
def update_specialty(
    specialty_id: int, data: SpecialtyUpdate, db: Session = Depends(get_session)
):
    """Update specialty details."""
    specialty = db.get(TherapistSpecialty, specialty_id)
    if not specialty:
        raise HTTPException(status_code=404, detail="Specialty not found")

    # Update fields if provided
    if data.name is not None:
        # Check name uniqueness if changing
        if data.name != specialty.name:
            existing = db.exec(
                select(TherapistSpecialty).where(TherapistSpecialty.name == data.name)
            ).first()
            if existing:
                raise HTTPException(
                    status_code=400, detail="Specialty name already exists"
                )
        specialty.name = data.name

    if data.description is not None:
        specialty.description = data.description

    if data.is_active is not None:
        specialty.is_active = data.is_active

    db.add(specialty)
    db.commit()
    db.refresh(specialty)

    return SpecialtyResponse(
        id=specialty.id,
        name=specialty.name,
        description=specialty.description,
        is_active=specialty.is_active,
    )


@router.delete("/{specialty_id}", status_code=204)
def delete_specialty(specialty_id: int, db: Session = Depends(get_session)):
    """Soft-delete specialty (set is_active=false)."""
    specialty = db.get(TherapistSpecialty, specialty_id)
    if not specialty:
        raise HTTPException(status_code=404, detail="Specialty not found")

    specialty.is_active = False
    db.add(specialty)
    db.commit()
    return None
