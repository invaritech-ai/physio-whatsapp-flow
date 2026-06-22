"""Pydantic schemas for Therapist endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.api.v1.schemas.specialty import SpecialtyResponse


class TherapistCreate(BaseModel):
    """Request schema for creating therapist."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "dr.smith@clinic.com",
                "display_name": "Dr. Smith",
                "license_number": "PT203315",
                "is_female": False,
                "calendly_user_uri": "https://api.calendly.com/users/XXXXX",
            }
        }
    )

    # Optional: when omitted (admin-provisioned therapist), the account is created
    # with a pending sentinel sub and linked to the real Neon identity by email on
    # first login. Callers that already hold a Neon sub may still pass it.
    neon_auth_sub: str | None = Field(default=None, min_length=1, description="Neon Auth subject ID")
    email: EmailStr = Field(..., description="Therapist email (unique)")
    display_name: str = Field(..., min_length=1, max_length=100)
    license_number: str | None = Field(default=None, min_length=3, max_length=64)
    is_female: bool = False
    calendly_user_uri: str | None = Field(None, description="Calendly user URI")
    # Optional: when provided, the therapist is set up via Calendly at create time —
    # the PAT is validated + stored encrypted so the therapist is immediately bookable.
    calendly_pat: str | None = Field(default=None, min_length=1, description="Calendly Personal Access Token")
    # Optional explicit slot mapping {duration_minutes(str): scheduling_url}. When given
    # (with calendly_pat), event types are created from it; otherwise they are auto-synced.
    slot_mapping: dict[str, str] | None = Field(default=None, description="Map of duration -> Calendly scheduling URL")
    # Session lengths (duration minutes as strings) the therapist offers, with no
    # booking link yet. Used by the admin create flow; links are added later via edit.
    slot_durations: list[str] | None = Field(default=None, description="Session lengths offered, no URL yet")
    # Optional per-duration therapist payout in cents, keyed by duration minutes.
    slot_payouts: dict[str, int] | None = Field(default=None, description="Map of duration -> therapist payout in cents")


class TherapistUpdate(BaseModel):
    """Request schema for updating therapist."""

    display_name: str | None = Field(None, min_length=1, max_length=100)
    license_number: str | None = Field(default=None, min_length=3, max_length=64)
    is_active: bool | None = None
    is_female: bool | None = None
    calendly_user_uri: str | None = None


class SpecialtyAssignment(BaseModel):
    """Request schema for assigning specialty to therapist."""

    specialty_id: int = Field(..., gt=0)


class AdminValidateCalendlyForTherapistRequest(BaseModel):
    """Admin validate request; uses the therapist's stored PAT unless one is given."""

    calendly_pat: str | None = Field(default=None, min_length=1)


class AdminSlotMappingUpdateRequest(BaseModel):
    """Admin update of a therapist's booking-link slot mapping + per-slot prices."""

    slot_mapping: dict[str, str] = Field(..., description="duration -> Calendly scheduling URL")
    slot_payouts: dict[str, int] | None = Field(default=None, description="duration -> therapist payout in cents")
    # Optional: only needed when the therapist has no stored Calendly PAT yet.
    calendly_pat: str | None = Field(default=None, min_length=1)


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
