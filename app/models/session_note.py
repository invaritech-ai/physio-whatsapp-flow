from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class SessionNote(SQLModel, table=True):
    """Therapist notes for a session."""

    __tablename__ = "session_note"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="session.id", index=True)
    author_user_id: int = Field(foreign_key="user.id", index=True)
    note_text: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    is_read: bool = Field(default=False)
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
