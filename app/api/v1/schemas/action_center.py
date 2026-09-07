"""Schemas for admin action center summary."""

from datetime import datetime

from pydantic import BaseModel, Field


class AdminActionCenterDebugIds(BaseModel):
    """Optional debug IDs for card-to-table parity verification."""

    pending_access_request_ids: list[int] = Field(default_factory=list)
    # Client IDs missing an active plan assignment, keyed by str(duration_minutes).
    clients_missing_plan_ids_by_duration: dict[str, list[int]] = Field(default_factory=dict)
    clients_missing_any_plan_assignment_ids: list[int] = Field(default_factory=list)
    past_sessions_missing_payment_record_ids: list[int] = Field(default_factory=list)
    active_clients_missing_financial_profile_ids: list[int] = Field(default_factory=list)


class AdminActionCenterSummaryResponse(BaseModel):
    """Aggregated admin dashboard action counters."""

    as_of: datetime
    lookback_days: int
    financial_alert_threshold_cents: int
    active_clients_in_window: int
    pending_access_requests: int
    therapists_missing_license: int
    therapists_missing_calendly: int
    therapists_missing_specialties: int
    # Count of active clients missing an active plan assignment, keyed by str(duration_minutes).
    clients_missing_plan_by_duration: dict[str, int]
    active_clients_missing_any_plan_assignment: int
    clients_with_receipting_backlog: int
    past_sessions_missing_payment_record: int
    active_clients_missing_financial_profile: int
    # Untriaged ("new") appointment-change notifications awaiting admin review (req 2.9).
    appointment_cancellations_pending_review: int = 0
    appointment_reschedules_pending_review: int = 0
    debug_ids: AdminActionCenterDebugIds | None = None
