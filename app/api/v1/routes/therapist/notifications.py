"""Therapist notification feed endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, func, select

from app.api.v1.schemas.therapist_notification import (
    TherapistNotificationItem,
    TherapistNotificationListResponse,
)
from app.core.auth import get_current_therapist
from app.db.session import get_session
from app.models import AuthEvent, Therapist

router = APIRouter(prefix="/therapist/notifications", tags=["Therapist Notifications"])


def _title_and_message(event: AuthEvent, details: dict | None) -> tuple[str, str]:
    if event.event_type == "therapist.notification.booking_confirmed":
        therapist_name = (details or {}).get("therapist_name") or "your calendar"
        client_name = (details or {}).get("client_name") or "A client"
        start_time = (details or {}).get("start_time_local") or "a new time slot"
        return (
            "New booking confirmed",
            f"{client_name} booked with {therapist_name} at {start_time}.",
        )
    if event.event_type == "therapist.notification.booking_cancelled":
        client_name = (details or {}).get("client_name") or "A client"
        start_time = (details or {}).get("start_time_local") or "a session"
        return (
            "Booking cancelled",
            f"{client_name} cancelled the booking at {start_time}.",
        )
    if event.event_type == "therapist.notification.booking_rescheduled":
        client_name = (details or {}).get("client_name") or "A client"
        start_time = (details or {}).get("start_time_local") or "an updated time"
        return (
            "Booking rescheduled",
            f"{client_name} rescheduled to {start_time}.",
        )
    return ("System notification", event.reason or "You have a new notification.")


@router.get("", response_model=TherapistNotificationListResponse)
def list_therapist_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
):
    stmt = (
        select(AuthEvent)
        .where(
            AuthEvent.user_id == therapist.user_id,
            AuthEvent.event_type.like("therapist.notification.%"),
        )
        .order_by(AuthEvent.created_at.desc(), AuthEvent.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list(db.exec(stmt).all())
    total = db.exec(
        select(func.count())
        .select_from(AuthEvent)
        .where(
            AuthEvent.user_id == therapist.user_id,
            AuthEvent.event_type.like("therapist.notification.%"),
        )
    ).one()

    items: list[TherapistNotificationItem] = []
    for row in rows:
        details = None
        if row.details_json:
            try:
                loaded = json.loads(row.details_json)
                details = loaded if isinstance(loaded, dict) else None
            except Exception:
                details = None
        title, message = _title_and_message(row, details)
        items.append(
            TherapistNotificationItem(
                id=row.id or 0,
                event_type=row.event_type,
                title=title,
                message=message,
                details=details,
                created_at=row.created_at,
            )
        )

    return TherapistNotificationListResponse(
        items=items,
        total=int(total),
        limit=limit,
        offset=offset,
        has_more=offset + limit < int(total),
    )
