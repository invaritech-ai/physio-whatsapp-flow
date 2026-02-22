from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

from sqlmodel import Field, SQLModel


class Session(SQLModel, table=True):
    """
    Therapy session (replaces Appointment).
    Created by Calendly webhook or manually via admin.
    """

    id: int | None = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    therapist_id: int = Field(foreign_key="therapist.id", index=True)
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    status: str = Field(default="scheduled")  # scheduled|started|completed|cancelled|no_show
    source: str  # "calendly" or "manual"
    charge_amount_cents: int | None = None  # Amount to charge in cents
    currency: str = Field(default="HKD")
    calendly_event_uri: str | None = Field(default=None, unique=True, index=True)
    calendly_invitee_uri: str | None = Field(default=None, index=True)
    reminder_sent: bool = Field(default=False)
    therapist_notified: bool = Field(default=False)
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
    updated_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
