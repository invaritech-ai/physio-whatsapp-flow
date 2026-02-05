from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class SessionNote(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    appointment_id: int = Field(foreign_key="appointment.id")
    note_text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = Field(default="physio")
