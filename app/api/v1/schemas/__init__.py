"""API v1 schemas - export all request/response models."""

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
