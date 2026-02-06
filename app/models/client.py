from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

from sqlmodel import Field, SQLModel


class Client(SQLModel, table=True):
    """WhatsApp customer, identified by phone number."""

    id: int | None = Field(default=None, primary_key=True)
    phone_e164: str = Field(unique=True, index=True)  # E.164 format: +85212345678
    name: str | None = None
    conversation_state: str = Field(default="IDLE")
    conversation_data: str | None = Field(default=None)  # JSON string for IVR multi-step data
    preferred_therapist_id: int | None = Field(default=None, foreign_key="therapist.id")
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
    updated_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
