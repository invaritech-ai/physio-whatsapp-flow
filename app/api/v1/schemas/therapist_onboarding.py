"""Pydantic schemas for therapist self-service onboarding endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# Nested schemas


class EventTypeInfo(BaseModel):
    """Event type information for responses."""

    model_config = ConfigDict(from_attributes=True)

    duration_minutes: int
    name: str | None = None
    scheduling_url: str


class EventTypeDetail(BaseModel):
    """Detailed event type information with ID."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    duration_minutes: int
    scheduling_url: str
    is_active: bool


class SpecialtyInfo(BaseModel):
    """Specialty information for responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


# Request schemas


class CompleteOnboardingRequest(BaseModel):
    """Request to complete therapist onboarding."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "calendly_pat": "eyJraWQiOiIxY2UxZTEzNj...",
                "specialty_ids": [1, 2, 3],
            }
        }
    )

    calendly_pat: str = Field(..., min_length=1, description="Calendly Personal Access Token")
    specialty_ids: list[int] = Field(..., min_length=1, description="List of specialty IDs to assign")


class ValidateCalendlyRequest(BaseModel):
    """Request to validate Calendly PAT."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "calendly_pat": "eyJraWQiOiIxY2UxZTEzNj...",
            }
        }
    )

    calendly_pat: str = Field(..., min_length=1, description="Calendly Personal Access Token")


class UpdateSpecialtiesRequest(BaseModel):
    """Request to update therapist specialties."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "specialty_ids": [1, 3, 5],
            }
        }
    )

    specialty_ids: list[int] = Field(..., min_length=1, description="List of specialty IDs to assign")


# Response schemas


class CompleteOnboardingResponse(BaseModel):
    """Response after completing onboarding."""

    therapist_id: int
    display_name: str
    calendly_user_uri: str
    is_active: bool
    specialties: list[SpecialtyInfo]
    event_types_synced: int
    event_types: list[EventTypeInfo]


class OnboardingStatusResponse(BaseModel):
    """Response showing onboarding completion status."""

    is_onboarded: bool
    has_calendly_uri: bool
    has_event_types: bool
    event_types_count: int
    has_specialties: bool
    specialties_count: int
    is_active: bool
    missing_steps: list[str]


class ValidateCalendlyResponse(BaseModel):
    """Response after validating Calendly PAT."""

    valid: bool
    user_uri: str | None = None
    name: str | None = None
    email: str | None = None
    event_types_found: int = 0
    event_types: list[EventTypeInfo] = []
    warnings: list[str] = []


class EventTypeSyncResponse(BaseModel):
    """Response after syncing event types."""

    event_types_synced: int
    event_types: list[EventTypeInfo]


class UpdateSpecialtiesResponse(BaseModel):
    """Response after updating specialties."""

    specialties: list[SpecialtyInfo]


class TherapistProfileResponse(BaseModel):
    """Complete therapist profile response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    display_name: str
    email: str | None = None
    is_active: bool
    calendly_user_uri: str | None = None
    specialties: list[SpecialtyInfo]
    event_types: list[EventTypeDetail]
    created_at: datetime
