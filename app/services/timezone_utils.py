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


# Common calling-code -> IANA timezone, longest prefix wins. Only single-timezone
# countries (or ones where a canonical zone is acceptable) are listed; multi-zone
# countries like the US/Australia are deliberately omitted so we fall back rather
# than guess wrong.
_PHONE_PREFIX_TIMEZONES: dict[str, str] = {
    "+852": "Asia/Hong_Kong",
    "+853": "Asia/Macau",
    "+886": "Asia/Taipei",
    "+86": "Asia/Shanghai",
    "+91": "Asia/Kolkata",
    "+65": "Asia/Singapore",
    "+60": "Asia/Kuala_Lumpur",
    "+66": "Asia/Bangkok",
    "+63": "Asia/Manila",
    "+62": "Asia/Jakarta",
    "+81": "Asia/Tokyo",
    "+82": "Asia/Seoul",
    "+84": "Asia/Ho_Chi_Minh",
    "+971": "Asia/Dubai",
    "+44": "Europe/London",
    "+33": "Europe/Paris",
    "+49": "Europe/Berlin",
    "+64": "Pacific/Auckland",
}


def infer_timezone_from_phone(phone_e164: str | None) -> str | None:
    """Best-effort IANA timezone from an E.164 phone's country code."""
    if not phone_e164:
        return None
    number = phone_e164.strip()
    for prefix in sorted(_PHONE_PREFIX_TIMEZONES, key=len, reverse=True):
        if number.startswith(prefix):
            return _PHONE_PREFIX_TIMEZONES[prefix]
    return None


def resolve_client_timezone(
    client_phone_e164: str | None,
    fallback_timezone: str | None,
) -> str:
    """Timezone for client-facing time display.

    Precedence: phone country-code inference > provided fallback (usually the
    therapist's timezone) > app default.
    """
    for candidate in (
        infer_timezone_from_phone(client_phone_e164),
        fallback_timezone,
        settings.invoice_timezone,
    ):
        if candidate and candidate.strip():
            return candidate.strip()
    return "UTC"


def normalize_query_datetime(value: datetime | None) -> datetime | None:
    """
    Normalize query datetime into DB-comparable UTC-naive datetime.

    Session timestamps are stored as UTC-naive in the current schema.
    """
    if value is None:
        return None
    return as_utc(value).replace(tzinfo=None)
