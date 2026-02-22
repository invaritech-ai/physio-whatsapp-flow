"""Schemas for admin self-service profile settings."""

from pydantic import BaseModel, ConfigDict, Field


class AdminPreferredTimezoneResponse(BaseModel):
    """Response payload for admin timezone read endpoint."""

    preferred_timezone: str | None = None


class UpdateAdminPreferredTimezoneRequest(BaseModel):
    """Request payload for admin timezone update endpoint."""

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


class UpdateAdminPreferredTimezoneResponse(BaseModel):
    """Response payload after admin timezone update."""

    preferred_timezone: str
    message: str = "Preferred timezone updated successfully"
