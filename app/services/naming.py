from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings


_FIXED_SUFFIX = "MOVEMENT_PHYSIOTHERAPY_RECEIPT"


def _invoice_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.invoice_timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _safe_filename_part(value: str | None, *, fallback: str) -> str:
    if not value:
        return fallback

    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")

    return value or fallback


def invoice_filename(
    *,
    invoice_id: int,
    client_name: str | None,
    date_value: datetime | None = None,
) -> str:
    dt = date_value or datetime.now(timezone.utc)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    local_dt = dt.astimezone(_invoice_timezone())
    date_part = local_dt.strftime("%Y-%m-%d")
    client_part = _safe_filename_part(client_name, fallback=f"client-{invoice_id}")

    return f"{client_part}_{date_part}_{_FIXED_SUFFIX}_{invoice_id}.pdf"
