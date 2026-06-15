"""Schemas for admin in-app notifications."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AdminNotificationItem(BaseModel):
    id: int
    event_type: str
    title: str
    message: str
    details: dict[str, Any] | None = None
    created_at: datetime


class AdminNotificationListResponse(BaseModel):
    items: list[AdminNotificationItem]
    total: int
    limit: int
    offset: int
    has_more: bool
