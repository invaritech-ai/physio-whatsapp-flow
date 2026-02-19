from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class BillingPlan(SQLModel, table=True):
    """Admin-managed billing plan for a specific session duration."""

    __tablename__ = "billing_plan"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=120)
    duration_minutes: int = Field(index=True)
    amount_cents: int
    currency: str = Field(default="HKD", max_length=8)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
    updated_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))


class ClientPlanAssignment(SQLModel, table=True):
    """Active plan assignment per client and duration."""

    __tablename__ = "client_plan_assignment"  # type: ignore
    __table_args__ = (
        sa.UniqueConstraint(
            "client_id",
            "duration_minutes",
            name="uq_client_plan_assignment_client_duration",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    duration_minutes: int = Field(index=True)
    billing_plan_id: int = Field(foreign_key="billing_plan.id", index=True)
    assigned_by_user_id: int = Field(foreign_key="user.id", index=True)
    effective_from: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
    notes: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
    updated_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
