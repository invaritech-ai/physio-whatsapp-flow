from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    """Staff user (therapist or admin) authenticated via Neon Auth."""

    id: int | None = Field(default=None, primary_key=True)
    neon_auth_sub: str = Field(unique=True, index=True)  # Neon Auth subject ID
    email: str = Field(unique=True, index=True)
    display_name: str
    role: str  # "admin" or "therapist"
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
    updated_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
