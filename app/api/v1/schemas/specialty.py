"""Pydantic schemas for TherapistSpecialty endpoints."""

from pydantic import BaseModel, ConfigDict, Field


class SpecialtyCreate(BaseModel):
    """Request schema for creating specialty."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Sports Rehabilitation",
                "description": "Treatment for sports injuries and athletic performance",
            }
        }
    )

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)


class SpecialtyUpdate(BaseModel):
    """Request schema for updating specialty."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class SpecialtyResponse(BaseModel):
    """Response schema for specialty."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    is_active: bool
