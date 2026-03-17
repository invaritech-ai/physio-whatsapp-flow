"""Helpers for capturing and resolving pre-Calendly booking choices."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, desc, select

from app.models import BookingIntent, Client

BOOKING_INTENT_LOOKBACK = timedelta(hours=24)


def normalize_phone_e164(phone_number: str) -> str:
    """Normalize phone numbers to a basic E.164-ish shape."""
    normalized = re.sub(r"[\s\-()]", "", phone_number.replace("whatsapp:", ""))
    if not normalized:
        raise ValueError("Phone number is required")
    if not normalized.startswith("+"):
        normalized = f"+{normalized}"
    return normalized


def resolve_client_phone(
    db: Session,
    *,
    client_id: int | None = None,
    client_phone_e164: str | None = None,
) -> str:
    """Resolve a normalized client phone using either a client id or raw phone."""
    if client_phone_e164:
        return normalize_phone_e164(client_phone_e164)

    if client_id is None:
        raise ValueError("Either client_id or client_phone_e164 is required")

    client = db.get(Client, client_id)
    if not client or not client.phone_e164:
        raise ValueError("Client phone number could not be resolved")
    return normalize_phone_e164(client.phone_e164)


def create_booking_intent(
    db: Session,
    *,
    therapist_id: int,
    duration_minutes: int,
    calendly_event_type_uri: str,
    scheduling_url: str,
    source: str,
    client_id: int | None = None,
    client_phone_e164: str | None = None,
) -> BookingIntent:
    """Persist the chosen business slot before the client goes to Calendly."""
    intent = BookingIntent(
        therapist_id=therapist_id,
        client_id=client_id,
        client_phone_e164=resolve_client_phone(
            db,
            client_id=client_id,
            client_phone_e164=client_phone_e164,
        ),
        duration_minutes=duration_minutes,
        calendly_event_type_uri=calendly_event_type_uri,
        scheduling_url=scheduling_url,
        source=source,
    )
    db.add(intent)
    db.flush()
    return intent


def find_recent_booking_intent(
    db: Session,
    *,
    therapist_id: int,
    client_phone_e164: str,
    calendly_event_type_uri: str,
) -> BookingIntent | None:
    """Return the newest unconsumed booking intent for the same therapist/client/URI."""
    cutoff = datetime.now(timezone.utc) - BOOKING_INTENT_LOOKBACK
    normalized_phone = normalize_phone_e164(client_phone_e164)
    return db.exec(
        select(BookingIntent)
        .where(
            BookingIntent.therapist_id == therapist_id,
            BookingIntent.client_phone_e164 == normalized_phone,
            BookingIntent.calendly_event_type_uri == calendly_event_type_uri,
            BookingIntent.consumed_at.is_(None),  # type: ignore[union-attr]
            BookingIntent.created_at >= cutoff,
        )
        .order_by(desc(BookingIntent.created_at), desc(BookingIntent.id))
    ).first()


def consume_booking_intent(intent: BookingIntent) -> None:
    """Mark an intent as consumed after it has been used for a real booking."""
    intent.consumed_at = datetime.now(timezone.utc)
