"""Pydantic schemas for therapist self-service onboarding endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Nested schemas


class EventTypeInfo(BaseModel):
    """Event type information for responses."""

    model_config = ConfigDict(from_attributes=True)

    calendly_event_type_uri: str
    duration_minutes: int
    name: str | None = None
    scheduling_url: str


class EventTypeDetail(BaseModel):
    """Detailed event type information with ID."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None
    calendly_event_type_uri: str
    duration_minutes: int
    scheduling_url: str
    is_active: bool


class SpecialtyInfo(BaseModel):
    """Specialty information for responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None
    name: str


class SlotMappingInfo(BaseModel):
    """Slot mapping: duration to event type details."""

    duration_minutes: int
    calendly_event_type_uri: str
    scheduling_url: str


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

    calendly_pat: str = Field(
        ..., min_length=1, description="Calendly Personal Access Token"
    )
    specialty_ids: list[int] = Field(
        ..., min_length=1, description="List of specialty IDs to assign"
    )


class ValidateCalendlyRequest(BaseModel):
    """Request to validate Calendly PAT."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "calendly_pat": "eyJraWQiOiIxY2UxZTEzNj...",
            }
        }
    )

    calendly_pat: str = Field(
        ..., min_length=1, description="Calendly Personal Access Token"
    )


class UpdateProfileRequest(BaseModel):
    """Request to update therapist profile (name)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "display_name": "Dr. Sarah Smith",
                "license_number": "PT203315",
            }
        }
    )

    display_name: str = Field(
        ..., min_length=1, max_length=100, description="Therapist display name"
    )
    license_number: str | None = Field(
        default=None,
        min_length=3,
        max_length=64,
        description="Therapist license number",
    )


class UpdatePreferredTimezoneRequest(BaseModel):
    """Request to update therapist preferred timezone."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "preferred_timezone": "Asia/Hong_Kong",
            }
        }
    )

    preferred_timezone: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="IANA timezone identifier (e.g., Asia/Hong_Kong).",
    )


class UpdateSpecialtiesRequest(BaseModel):
    """Request to update therapist specialties.

    Accepts existing specialty IDs and/or new specialty names.
    New names are auto-created as specialties. At least one must be provided.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "specialty_ids": [1, 3],
                "new_specialties": ["Sports Rehab", "Neurological"],
            }
        }
    )

    specialty_ids: list[int] = Field(
        default=[], description="List of existing specialty IDs to assign"
    )
    new_specialties: list[str] = Field(
        default=[], description="List of new specialty names to create and assign"
    )

    @model_validator(mode="after")
    def at_least_one_specialty(self) -> "UpdateSpecialtiesRequest":
        if not self.specialty_ids and not self.new_specialties:
            raise ValueError("At least one specialty_id or new_specialty name is required")
        return self


class SaveCalendlyRequest(BaseModel):
    """Request to save Calendly PAT with explicit slot mapping."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "calendly_pat": "eyJraWQiOiIxY2UxZTEzNj...",
                "slot_mapping": {
                    "30": "https://api.calendly.com/event_types/AAA",
                    "45": "https://api.calendly.com/event_types/BBB",
                    "60": "https://api.calendly.com/event_types/CCC",
                },
            }
        }
    )

    calendly_pat: str = Field(
        ..., min_length=1, description="Calendly Personal Access Token"
    )
    slot_mapping: dict[str, str] = Field(
        ...,
        description="Mapping of duration (minutes) to Calendly event type URI. Required keys: '30', '45', '60'.",
    )

    @model_validator(mode="after")
    def validate_slot_mapping(self) -> "SaveCalendlyRequest":
        required_keys = {"30", "45", "60"}
        provided_keys = set(self.slot_mapping.keys())
        missing = required_keys - provided_keys
        if missing:
            raise ValueError(f"Missing required durations: {', '.join(sorted(missing))}")
        extra = provided_keys - required_keys
        if extra:
            raise ValueError(f"Unexpected durations: {', '.join(sorted(extra))}. Only 30, 45, 60 allowed.")
        return self


class CalendlyWebhookActionRequest(BaseModel):
    """Optional PAT override for Calendly webhook check/register actions."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "calendly_pat": "eyJraWQiOiIxY2UxZTEzNj...",
            }
        }
    )

    calendly_pat: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Optional Calendly PAT override. If omitted, backend uses stored encrypted PAT."
        ),
    )


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
    has_profile_name: bool
    has_license_number: bool
    has_specialties: bool
    specialties_count: int
    has_calendly_uri: bool
    has_slot_mapping: bool
    has_event_types: bool
    event_types_count: int
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


class UpdateProfileResponse(BaseModel):
    """Response after updating profile."""

    display_name: str
    license_number: str | None = None
    message: str = "Profile updated successfully"


class UpdatePreferredTimezoneResponse(BaseModel):
    """Response after updating preferred timezone."""

    preferred_timezone: str
    message: str = "Preferred timezone updated successfully"


class UpdateSpecialtiesResponse(BaseModel):
    """Response after updating specialties."""

    specialties: list[SpecialtyInfo]
    message: str = "Specialties updated successfully"


class SaveCalendlyResponse(BaseModel):
    """Response after saving Calendly PAT with slot mapping."""

    calendly_user_uri: str
    slot_mapping: list[SlotMappingInfo]
    is_active: bool
    message: str = "Calendly connected and account activated"


class CalendlyWebhookSubscriptionInfo(BaseModel):
    """Webhook subscription info from Calendly."""

    uri: str | None = None
    scope: str | None = None
    state: str | None = None
    callback_url: str
    events: list[str] = []


class CalendlyWebhookCheckResponse(BaseModel):
    """Response for webhook registration check."""

    endpoint_url: str
    user_uri: str
    organization_uri: str
    has_matching_webhook: bool
    needs_registration: bool
    missing_events: list[str] = []
    subscriptions: list[CalendlyWebhookSubscriptionInfo] = []
    warnings: list[str] = []


class CalendlyWebhookRegisterResponse(CalendlyWebhookCheckResponse):
    """Response for webhook registration action."""

    created: bool
    created_webhook_uri: str | None = None
    signing_key: str | None = None


class TherapistProfileResponse(BaseModel):
    """Complete therapist profile response."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None
    user_id: int
    display_name: str | None = None
    license_number: str | None = None
    preferred_timezone: str | None = None
    email: str | None = None
    is_active: bool
    calendly_user_uri: str | None = None
    specialties: list[SpecialtyInfo]
    event_types: list[EventTypeDetail]
    slot_mapping: list[SlotMappingInfo] = []
    created_at: datetime
