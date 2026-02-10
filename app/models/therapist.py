from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

from sqlmodel import Field, SQLModel


class Therapist(SQLModel, table=True):
    """Therapist profile linked to a User account."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True, index=True)
    display_name: str | None = None
    is_active: bool = Field(default=True)
    calendly_user_uri: str | None = None  # e.g., "https://api.calendly.com/users/XXXXX"
    calendly_pat_encrypted: str | None = None  # Encrypted Calendly Personal Access Token
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
