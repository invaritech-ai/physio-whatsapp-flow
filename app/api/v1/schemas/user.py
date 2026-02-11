"""Pydantic schemas for admin user management endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserListResponse(BaseModel):
    """Response schema for listing approved users."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str | None
    role: str
    is_active: bool
    has_therapist_profile: bool
    created_at: datetime


class UpdateRoleRequest(BaseModel):
    """Request schema for changing a user's role."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "role": "admin",
            }
        }
    )

    role: str = Field(
        ..., pattern="^(admin|therapist)$", description="New role: 'admin' or 'therapist'"
    )


class UpdateRoleResponse(BaseModel):
    """Response schema after changing a user's role."""

    user_id: int
    email: str
    previous_role: str
    new_role: str
    therapist_id: int | None = None
    message: str


class UpdateUserStatusRequest(BaseModel):
    """Request schema for activating or suspending a user account."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "is_active": False,
            }
        }
    )

    is_active: bool = Field(..., description="Set to false to suspend, true to reactivate")


class UpdateUserStatusResponse(BaseModel):
    """Response schema after changing active status."""

    user_id: int
    email: str
    previous_is_active: bool
    new_is_active: bool
    message: str


class RevokeSessionsRequest(BaseModel):
    """Request schema for manually revoking a user's sessions."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reason": "security_incident",
            }
        }
    )

    reason: str | None = Field(default=None, max_length=255)


class RevokeSessionsResponse(BaseModel):
    """Response schema after session revocation."""

    user_id: int
    email: str
    revoked_at: datetime
    message: str
