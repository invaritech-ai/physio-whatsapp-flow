# Phase 2.5: Admin APIs - Implementation Plan

## Context

Phase 2 (WhatsApp Bot) is complete, but we cannot:
- Test the bot flow (no therapists/specialties in DB)
- Build Phase 3 matching (need Calendly links configured)
- Enable frontend therapist management

Phase 2.5 builds minimal CRUD APIs for therapists and specialties. Auth is deferred to Phase 6 to prioritize feature delivery.

---

## Architecture Overview

### API Structure
```
POST /api/v1/admin/therapists          Create therapist + user
GET  /api/v1/admin/therapists           List all therapists
GET  /api/v1/admin/therapists/{id}      Get therapist detail
PATCH /api/v1/admin/therapists/{id}     Update therapist
DELETE /api/v1/admin/therapists/{id}    Soft-delete therapist

POST /api/v1/admin/specialties          Create specialty
GET  /api/v1/admin/specialties          List specialties
PATCH /api/v1/admin/specialties/{id}    Update specialty
DELETE /api/v1/admin/specialties/{id}   Soft-delete specialty

POST /api/v1/admin/therapists/{id}/specialties              Assign specialty
DELETE /api/v1/admin/therapists/{id}/specialties/{sid}     Remove specialty
GET  /api/v1/admin/therapists/{id}/specialties              List specialties
```

### Data Flow
```
Frontend (JWT token) → FastAPI Endpoint → Validate → DB → Response
                          ↓
                     (Auth deferred to Phase 6)
```

---

## Implementation Approach

### File Structure
```
app/api/v1/
  schemas/
    __init__.py                  # Export all schemas
    therapist.py                 # TherapistCreate, Update, Response
    specialty.py                 # SpecialtyCreate, Update, Response
  routes/
    admin/
      __init__.py                # Export router
      therapists.py              # Therapist CRUD endpoints
      specialties.py             # Specialty CRUD endpoints

tests/
  test_admin_therapists.py       # Therapist API tests
  test_admin_specialties.py      # Specialty API tests
```

---

## Critical Files Implementation

### 1. `app/api/v1/schemas/therapist.py`
```python
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

from app.api.v1.schemas.specialty import SpecialtyResponse


class TherapistCreate(BaseModel):
    """Request schema for creating therapist."""
    neon_auth_sub: str = Field(..., min_length=1, description="Neon Auth subject ID")
    email: EmailStr = Field(..., description="Therapist email (unique)")
    display_name: str = Field(..., min_length=1, max_length=100)
    calendly_link: str | None = Field(None, description="Calendly scheduling URL")

    class Config:
        json_schema_extra = {
            "example": {
                "neon_auth_sub": "auth-therapist-123",
                "email": "dr.smith@clinic.com",
                "display_name": "Dr. Smith",
                "calendly_link": "https://calendly.com/dr-smith"
            }
        }


class TherapistUpdate(BaseModel):
    """Request schema for updating therapist."""
    display_name: str | None = Field(None, min_length=1, max_length=100)
    is_active: bool | None = None
    calendly_link: str | None = None


class SpecialtyAssignment(BaseModel):
    """Request schema for assigning specialty to therapist."""
    specialty_id: int = Field(..., gt=0)


class TherapistResponse(BaseModel):
    """Response schema for therapist."""
    id: int
    user_id: int
    display_name: str
    is_active: bool
    calendly_link: str | None
    specialties: list[SpecialtyResponse]
    created_at: datetime

    class Config:
        from_attributes = True


class TherapistListResponse(BaseModel):
    """Response schema for list of therapists."""
    id: int
    display_name: str
    is_active: bool
    email: str  # From User relation
    specialty_count: int

    class Config:
        from_attributes = True
```

### 2. `app/api/v1/schemas/specialty.py`
```python
from pydantic import BaseModel, Field


class SpecialtyCreate(BaseModel):
    """Request schema for creating specialty."""
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Sports Rehabilitation",
                "description": "Treatment for sports injuries and athletic performance"
            }
        }


class SpecialtyUpdate(BaseModel):
    """Request schema for updating specialty."""
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class SpecialtyResponse(BaseModel):
    """Response schema for specialty."""
    id: int
    name: str
    description: str | None
    is_active: bool

    class Config:
        from_attributes = True
```

### 3. `app/api/v1/routes/admin/therapists.py`
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import Therapist, TherapistSpecialtyMap, User
from app.api.v1.schemas.therapist import (
    TherapistCreate,
    TherapistUpdate,
    TherapistResponse,
    TherapistListResponse,
    SpecialtyAssignment,
)

router = APIRouter(prefix="/admin/therapists", tags=["Admin - Therapists"])


@router.post("", response_model=TherapistResponse, status_code=201)
def create_therapist(data: TherapistCreate, db: Session = Depends(get_session)):
    """
    Create a new therapist (with associated User record).

    Creates both User and Therapist records atomically.
    """
    # Check if email already exists
    existing_user = db.exec(select(User).where(User.email == data.email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

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
        calendly_link=data.calendly_link,
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
        is_active=therapist.is_active,
        calendly_link=therapist.calendly_link,
        specialties=[],
        created_at=therapist.created_at,
    )


@router.get("", response_model=list[TherapistListResponse])
def list_therapists(db: Session = Depends(get_session)):
    """List all therapists with basic info."""
    stmt = select(Therapist, User).join(User).order_by(Therapist.created_at.desc())
    results = db.exec(stmt).all()

    therapists = []
    for therapist, user in results:
        # Count specialties
        specialty_count = db.exec(
            select(TherapistSpecialtyMap).where(
                TherapistSpecialtyMap.therapist_id == therapist.id
            )
        ).all()

        therapists.append(
            TherapistListResponse(
                id=therapist.id,
                display_name=therapist.display_name,
                is_active=therapist.is_active,
                email=user.email,
                specialty_count=len(specialty_count),
            )
        )

    return therapists


@router.get("/{therapist_id}", response_model=TherapistResponse)
def get_therapist(therapist_id: int, db: Session = Depends(get_session)):
    """Get therapist detail with specialties."""
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")

    # Get specialties
    from app.models import TherapistSpecialty
    from app.api.v1.schemas.specialty import SpecialtyResponse

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
        is_active=therapist.is_active,
        calendly_link=therapist.calendly_link,
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
    therapist_id: int, data: TherapistUpdate, db: Session = Depends(get_session)
):
    """Update therapist details."""
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")

    # Update fields if provided
    if data.display_name is not None:
        therapist.display_name = data.display_name
    if data.is_active is not None:
        therapist.is_active = data.is_active
    if data.calendly_link is not None:
        therapist.calendly_link = data.calendly_link

    db.add(therapist)
    db.commit()
    db.refresh(therapist)

    # Return full response with specialties
    return get_therapist(therapist_id, db)


@router.delete("/{therapist_id}", status_code=204)
def delete_therapist(therapist_id: int, db: Session = Depends(get_session)):
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
    therapist_id: int, data: SpecialtyAssignment, db: Session = Depends(get_session)
):
    """Assign a specialty to a therapist."""
    from app.models import TherapistSpecialty

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
    therapist_id: int, specialty_id: int, db: Session = Depends(get_session)
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


@router.get("/{therapist_id}/specialties")
def list_therapist_specialties(therapist_id: int, db: Session = Depends(get_session)):
    """List all specialties assigned to a therapist."""
    from app.models import TherapistSpecialty
    from app.api.v1.schemas.specialty import SpecialtyResponse

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
```

### 4. `app/api/v1/routes/admin/specialties.py`
```python
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
def list_specialties(
    active_only: bool = False, db: Session = Depends(get_session)
):
    """List all specialties (optionally filter to active only)."""
    stmt = select(TherapistSpecialty).order_by(TherapistSpecialty.name)

    if active_only:
        stmt = stmt.where(TherapistSpecialty.is_active == True)

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
```

### 5. `app/api/v1/routes/admin/__init__.py`
```python
from fastapi import APIRouter

from app.api.v1.routes.admin import therapists, specialties

router = APIRouter()

router.include_router(therapists.router)
router.include_router(specialties.router)

__all__ = ["router"]
```

### 6. `app/api/v1/schemas/__init__.py`
```python
from app.api.v1.schemas.specialty import (
    SpecialtyCreate,
    SpecialtyUpdate,
    SpecialtyResponse,
)
from app.api.v1.schemas.therapist import (
    TherapistCreate,
    TherapistUpdate,
    TherapistResponse,
    TherapistListResponse,
    SpecialtyAssignment,
)

__all__ = [
    "SpecialtyCreate",
    "SpecialtyUpdate",
    "SpecialtyResponse",
    "TherapistCreate",
    "TherapistUpdate",
    "TherapistResponse",
    "TherapistListResponse",
    "SpecialtyAssignment",
]
```

### 7. Update `app/main.py`
```python
# Add after other imports
from app.api.v1.routes.admin import router as admin_router

# Add after other router includes
app.include_router(admin_router, prefix="/api/v1")
```

---

## Testing Strategy

### Test Files

**tests/test_admin_therapists.py**:
- Test create therapist (success)
- Test create duplicate email (400)
- Test list therapists
- Test get therapist detail
- Test update therapist
- Test soft delete therapist
- Test assign specialty
- Test assign duplicate specialty (400)
- Test remove specialty
- Test list therapist specialties

**tests/test_admin_specialties.py**:
- Test create specialty (success)
- Test create duplicate name (400)
- Test list specialties (all, active only)
- Test get specialty detail
- Test update specialty
- Test update to duplicate name (400)
- Test soft delete specialty

---

## Order of Implementation

### Day 1: Schemas + Specialty CRUD
1. Create `app/api/v1/schemas/specialty.py`
2. Create `app/api/v1/routes/admin/specialties.py`
3. Write `tests/test_admin_specialties.py`
4. Run tests, fix issues
5. Manual test via `/docs` (Swagger UI)

### Day 2: Therapist CRUD + Assignment
1. Create `app/api/v1/schemas/therapist.py`
2. Create `app/api/v1/routes/admin/therapists.py`
3. Write `tests/test_admin_therapists.py`
4. Run tests, fix issues
5. Manual test via `/docs`

### Day 3: Integration + Testing
1. Update `app/main.py` to register admin router
2. Create `app/api/v1/schemas/__init__.py`
3. Create `app/api/v1/routes/admin/__init__.py`
4. Run full test suite
5. Test with frontend (if available)
6. Create test data to enable Phase 2 bot testing

---

## Verification Checklist

Before marking Phase 2.5 complete:

- [ ] All tests pass (`pytest tests/test_admin_*.py`)
- [ ] Can create therapist via API
- [ ] Can assign specialties to therapist
- [ ] Soft deletes work (is_active=false)
- [ ] Duplicate email/name blocked
- [ ] Swagger UI (`/docs`) shows all endpoints
- [ ] Can create test data for Phase 2 bot testing
- [ ] Ready to add Calendly links for Phase 3

---

## Modified Files Summary

**New Files (8):**
- `app/api/v1/schemas/therapist.py`
- `app/api/v1/schemas/specialty.py`
- `app/api/v1/schemas/__init__.py`
- `app/api/v1/routes/admin/__init__.py`
- `app/api/v1/routes/admin/therapists.py`
- `app/api/v1/routes/admin/specialties.py`
- `tests/test_admin_therapists.py`
- `tests/test_admin_specialties.py`

**Modified Files (1):**
- `app/main.py` - Register admin router

**Total: ~800 new lines of code + tests**
