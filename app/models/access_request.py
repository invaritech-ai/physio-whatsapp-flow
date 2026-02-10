"""Access request model for pending user approvals."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

from sqlmodel import Field, SQLModel


class AccessRequest(SQLModel, table=True):
    """Track access requests from users who logged in via Neon Auth but don't have User records yet."""

    __tablename__ = "access_request"

    id: int | None = Field(default=None, primary_key=True)
    neon_auth_sub: str = Field(unique=True, index=True)  # From JWT "sub" claim
    email: str = Field(index=True)  # From JWT "email" claim
    status: str = Field(default="pending", index=True)  # "pending" | "approved" | "rejected"
    requested_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
    reviewed_at: datetime | None = Field(default=None)
    reviewed_by: int | None = Field(default=None)  # User ID of admin who reviewed
