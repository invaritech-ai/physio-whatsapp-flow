"""Schemas for admin action center summary."""

from datetime import datetime

from pydantic import BaseModel


class AdminActionCenterDebugIds(BaseModel):
    """Optional debug IDs for card-to-table parity verification."""

    pending_access_request_ids: list[int]
    clients_missing_plan_30_ids: list[int]
    clients_missing_plan_45_ids: list[int]
    clients_missing_any_plan_assignment_ids: list[int]
    past_sessions_missing_payment_record_ids: list[int]
    active_clients_missing_financial_profile_ids: list[int]


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
    clients_missing_plan_30: int
    clients_missing_plan_45: int
    active_clients_missing_any_plan_assignment: int
    clients_with_receipting_backlog: int
    past_sessions_missing_payment_record: int
    active_clients_missing_financial_profile: int
    debug_ids: AdminActionCenterDebugIds | None = None
