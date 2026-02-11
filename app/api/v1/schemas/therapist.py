"""Pydantic schemas for Therapist endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.api.v1.schemas.specialty import SpecialtyResponse


class TherapistCreate(BaseModel):
    """Request schema for creating therapist."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "neon_auth_sub": "auth-therapist-123",
                "email": "dr.smith@clinic.com",
                "display_name": "Dr. Smith",
                "calendly_user_uri": "https://api.calendly.com/users/XXXXX",
            }
        }
    )

    neon_auth_sub: str = Field(..., min_length=1, description="Neon Auth subject ID")
    email: EmailStr = Field(..., description="Therapist email (unique)")
    display_name: str = Field(..., min_length=1, max_length=100)
    calendly_user_uri: str | None = Field(None, description="Calendly user URI")


class TherapistUpdate(BaseModel):
    """Request schema for updating therapist."""

    display_name: str | None = Field(None, min_length=1, max_length=100)
    is_active: bool | None = None
    calendly_user_uri: str | None = None


class SpecialtyAssignment(BaseModel):
    """Request schema for assigning specialty to therapist."""

    specialty_id: int = Field(..., gt=0)


class TherapistResponse(BaseModel):
    """Response schema for therapist with full details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    display_name: str | None
    is_active: bool
    calendly_user_uri: str | None
    specialties: list[SpecialtyResponse]
    created_at: datetime


class TherapistListResponse(BaseModel):
    """Response schema for list of therapists (lightweight)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str | None
    is_active: bool
    email: str  # From User relation
    specialty_count: int
