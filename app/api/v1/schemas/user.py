"""Pydantic schemas for admin user management endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserListResponse(BaseModel):
    """Response schema for listing approved users."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
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
