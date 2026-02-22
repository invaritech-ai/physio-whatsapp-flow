"""Timezone helpers for API serialization and query normalization."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings


def as_utc(value: datetime) -> datetime:
    """Interpret naive datetimes as UTC and return timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_preferred_timezone(value: datetime, preferred_timezone: str | None) -> datetime:
    """Convert datetime to preferred timezone, defaulting to app timezone then UTC."""
    utc_value = as_utc(value)
    fallback_timezone = settings.invoice_timezone

    target_timezone = preferred_timezone or fallback_timezone
    normalized = target_timezone.strip()
    if not normalized:
        normalized = "UTC"

    try:
        return utc_value.astimezone(ZoneInfo(normalized))
    except ZoneInfoNotFoundError:
        return utc_value


def normalize_query_datetime(value: datetime | None) -> datetime | None:
    """
    Normalize query datetime into DB-comparable UTC-naive datetime.

    Session timestamps are stored as UTC-naive in the current schema.
    """
    if value is None:
        return None
    return as_utc(value).replace(tzinfo=None)
