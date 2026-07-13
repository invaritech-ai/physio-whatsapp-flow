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
                "license_number": "PT203315",
                "calendly_user_uri": "https://api.calendly.com/users/XXXXX",
            }
        }
    )

    neon_auth_sub: str = Field(..., min_length=1, description="Neon Auth subject ID")
    email: EmailStr = Field(..., description="Therapist email (unique)")
    display_name: str = Field(..., min_length=1, max_length=100)
    license_number: str | None = Field(default=None, min_length=3, max_length=64)
    calendly_user_uri: str | None = Field(None, description="Calendly user URI")


class TherapistUpdate(BaseModel):
    """Request schema for updating therapist."""

    display_name: str | None = Field(None, min_length=1, max_length=100)
    license_number: str | None = Field(default=None, min_length=3, max_length=64)
    is_active: bool | None = None
    is_female: bool | None = None
    calendly_user_uri: str | None = None


class TherapistPayoutUpdateRequest(BaseModel):
    """Admin request to set per-duration therapist payouts (compensation).

    Keys are string minutes (e.g. "15", "60"); values are payout in cents. Each
    duration must already have an active event type for the therapist.
    """

    payouts: dict[str, int] = Field(
        ..., description="Map of duration (minutes) -> therapist payout in cents"
    )


class SpecialtyAssignment(BaseModel):
    """Request schema for assigning specialty to therapist."""

    specialty_id: int = Field(..., gt=0)


class TherapistResponse(BaseModel):
    """Response schema for therapist with full details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    display_name: str | None
    license_number: str | None
    is_active: bool
    is_female: bool
    calendly_user_uri: str | None
    specialties: list[SpecialtyResponse]
    created_at: datetime


class TherapistListResponse(BaseModel):
    """Response schema for list of therapists (lightweight)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str | None
    license_number: str | None
    is_active: bool
    email: str  # From User relation
    specialty_count: int
    # When True, this account uses bot-only suspension: `is_active` reflects
    # WhatsApp-bot bookability only; login/dashboard stay available regardless.
    is_bot_only_suspend: bool = False
