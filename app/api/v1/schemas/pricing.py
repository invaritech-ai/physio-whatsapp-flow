"""Shared pricing schemas."""

from pydantic import BaseModel


class AssignedPlanSummary(BaseModel):
    """Compact plan summary exposed on session payloads."""

    plan_id: int
    plan_name: str
    duration_minutes: int
    amount_cents: int
    currency: str
