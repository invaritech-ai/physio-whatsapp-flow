from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class MatchingDecision(SQLModel, table=True):
    """Audit trail for matching engine decisions."""

    __tablename__ = "matching_decision"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    requested_duration: int | None = None
    requested_specialty: str | None = None
    requested_time_band: str | None = None
    requested_days: str | None = None  # JSON string list, e.g., "[1,2,3]" for Mon/Tue/Wed
    selected_therapist_id: int | None = Field(default=None, foreign_key="therapist.id")
    scoring_breakdown: str | None = None  # JSON string with scoring details
    rationale: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    fallback_level: int = Field(default=0)  # 0=full match, 1-3=fallback levels
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
