"""Pydantic schemas for auth event audit endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuthEventResponse(BaseModel):
    """Auth event row returned to admins."""

    id: int
    event_type: str
    user_id: int | None = None
    user_sub: str | None = None
    actor_user_id: int | None = None
    reason: str | None = None
    details: dict[str, Any] | None = None
    created_at: datetime
