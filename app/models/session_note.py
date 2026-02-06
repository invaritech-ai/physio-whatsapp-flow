from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class SessionNoteBase(SQLModel):
    """Shared fields — single source of truth for all SessionNote schemas."""

    appointment_id: int
    physio_id: int | None = None
    note_text: str
    created_by: str = "physio"


class SessionNote(SessionNoteBase, table=True):
    """Database table model — adds auto-generated and DB-specific fields."""

    id: int | None = Field(default=None, primary_key=True)
    appointment_id: int = Field(foreign_key="appointment.id")
    physio_id: int | None = Field(default=None, foreign_key="user.id")
    note_text: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
