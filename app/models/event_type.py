from __future__ import annotations

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class TherapistEventType(SQLModel, table=True):
    """Calendly event type mapping per therapist (e.g., 30min/45min/60min sessions)."""

    __tablename__ = "therapist_event_type"  # type: ignore
    __table_args__ = (
        sa.UniqueConstraint(
            "therapist_id",
            "duration_minutes",
            name="uq_therapist_event_type_therapist_duration",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    therapist_id: int = Field(foreign_key="therapist.id", index=True)
    calendly_event_type_uri: str | None = Field(default=None, index=True)  # e.g., "https://api.calendly.com/event_types/XXXXX"
    duration_minutes: int
    scheduling_url: str  # Public booking link
    is_active: bool = Field(default=True)
    # Optional per-therapist price for this session length. When set, it takes
    # precedence over client billing plans when resolving the expected charge.
    amount_cents: int | None = Field(default=None)
    currency: str | None = Field(default=None, max_length=8)
    # Optional therapist compensation (payout) for completing a session of this
    # duration — drives payroll. Independent of the client-facing amount_cents.
    payout_cents: int | None = Field(default=None)
