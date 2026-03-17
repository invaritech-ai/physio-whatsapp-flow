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
    calendly_event_type_uri: str = Field(index=True)  # e.g., "https://api.calendly.com/event_types/XXXXX"
    duration_minutes: int
    scheduling_url: str  # Public booking link
    is_active: bool = Field(default=True)
