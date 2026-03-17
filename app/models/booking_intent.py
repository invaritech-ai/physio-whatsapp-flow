from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

from sqlmodel import Field, SQLModel


class BookingIntent(SQLModel, table=True):
    """Tracks the business-slot choice made before redirecting to Calendly."""

    __tablename__ = "booking_intent"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    therapist_id: int = Field(foreign_key="therapist.id", index=True)
    client_id: int | None = Field(default=None, foreign_key="client.id", index=True)
    client_phone_e164: str = Field(index=True)
    duration_minutes: int
    calendly_event_type_uri: str = Field(index=True)
    scheduling_url: str
    source: str = Field(default="web")
    consumed_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc), index=True)
