"""Schemas for therapist/admin clinical note workflows."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClinicalNoteUpsertRequest(BaseModel):
    """Therapist request to upsert a clinical note for a session."""

    note_text: str = Field(min_length=1, max_length=12000)
    diagnosis: str | None = Field(default=None, max_length=2000)


class ClinicalNoteResponse(BaseModel):
    """Canonical clinical note response payload."""

    model_config = ConfigDict(from_attributes=True)

    session_id: int
    note_id: int
    note_text: str
    diagnosis: str | None
    author_user_id: int
    created_at: datetime
    updated_at: datetime
