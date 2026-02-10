"""Pydantic schemas for AccessRequest endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AccessRequestListResponse(BaseModel):
    """Response schema for listing access requests."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    neon_auth_sub: str
    email: str
    status: str  # "pending" | "approved" | "rejected"
    requested_at: datetime
    reviewed_at: datetime | None


class AccessRequestApprove(BaseModel):
    """Request schema for approving access request."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "role": "therapist",
                "display_name": "Dr. Sarah Johnson",
            }
        }
    )

    role: str = Field(..., description="User role: 'therapist' or 'admin'")
    display_name: str | None = Field(None, description="Display name (optional, defaults to email prefix)")


class AccessRequestApproveResponse(BaseModel):
    """Response schema for approved access request."""

    access_request_id: int
    user_id: int
    therapist_id: int | None
    email: str
    display_name: str
    role: str
    message: str
