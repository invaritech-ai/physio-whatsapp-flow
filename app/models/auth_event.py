"""Auth audit event model for security-relevant actions."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

from sqlmodel import Field, SQLModel


class AuthEvent(SQLModel, table=True):
    """Append-only audit log for auth actions and access decisions."""

    __tablename__ = "auth_event"

    id: int | None = Field(default=None, primary_key=True)
    event_type: str = Field(index=True)
    user_id: int | None = Field(default=None, index=True)
    user_sub: str | None = Field(default=None, index=True)
    actor_user_id: int | None = Field(default=None, index=True)
    reason: str | None = Field(default=None, index=True)
    details_json: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=partial(datetime.now, timezone.utc),
        index=True,
    )
