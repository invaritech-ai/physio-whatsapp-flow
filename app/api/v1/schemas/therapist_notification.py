"""Schemas for therapist in-app notifications."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TherapistNotificationItem(BaseModel):
    id: int
    event_type: str
    title: str
    message: str
    details: dict[str, Any] | None = None
    created_at: datetime


class TherapistNotificationListResponse(BaseModel):
    items: list[TherapistNotificationItem]
    total: int
    limit: int
    offset: int
    has_more: bool

