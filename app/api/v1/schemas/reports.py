"""Schemas for admin reports endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TherapistUtilizationItem(BaseModel):
    therapist_id: int
    therapist_name: str
    completed_sessions: int
    scheduled_sessions: int
    cancelled_sessions: int
    no_show_sessions: int
    utilized_minutes: int
    period_start: datetime
    period_end: datetime


class TherapistUtilizationListResponse(BaseModel):
    items: list[TherapistUtilizationItem]
    total: int
    limit: int
    offset: int
    has_more: bool


class TherapistPayrollItem(BaseModel):
    therapist_id: int
    therapist_name: str
    completed_sessions: int
    payable_minutes: int
    estimated_payable_cents: int
    currency: str
    period_start: datetime
    period_end: datetime


class TherapistPayrollListResponse(BaseModel):
    items: list[TherapistPayrollItem]
    total: int
    limit: int
    offset: int
    has_more: bool
