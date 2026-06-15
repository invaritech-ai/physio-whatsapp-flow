"""Admin notification feed endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, func, select

from app.api.v1.schemas.admin_notification import (
    AdminNotificationItem,
    AdminNotificationListResponse,
)
from app.core.auth import get_current_admin
from app.db.session import get_session
from app.models import AuthEvent, User

router = APIRouter(prefix="/admin/notifications", tags=["Admin Notifications"])

_ADMIN_NOTIFICATION_PREFIX = "admin.notification.%"


def _title_and_message(event: AuthEvent, details: dict | None) -> tuple[str, str]:
    client_name = (details or {}).get("client_name") or "A client"
    therapist_name = (details or {}).get("therapist_name") or "a therapist"
    start_time = (details or {}).get("start_time_local") or "a session"
    if event.event_type == "admin.notification.booking_cancelled":
        return (
            "Appointment cancelled",
            f"{client_name} cancelled their appointment with {therapist_name} at {start_time}.",
        )
    if event.event_type == "admin.notification.booking_rescheduled":
        return (
            "Appointment rescheduled",
            f"{client_name} rescheduled their appointment with {therapist_name} to {start_time}.",
        )
    return ("System notification", event.reason or "You have a new notification.")


@router.get("", response_model=AdminNotificationListResponse)
def list_admin_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """List the current admin's in-app notifications (cancel/reschedule, etc.)."""
    where = (
        AuthEvent.user_id == admin.id,
        AuthEvent.event_type.like(_ADMIN_NOTIFICATION_PREFIX),  # type: ignore[attr-defined]
    )
    rows = list(
        db.exec(
            select(AuthEvent)
            .where(*where)
            .order_by(AuthEvent.created_at.desc(), AuthEvent.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    total = db.exec(
        select(func.count()).select_from(AuthEvent).where(*where)
    ).one()

    items: list[AdminNotificationItem] = []
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
            AdminNotificationItem(
                id=row.id or 0,
                event_type=row.event_type,
                title=title,
                message=message,
                details=details,
                created_at=row.created_at,
            )
        )

    return AdminNotificationListResponse(
        items=items,
        total=int(total),
        limit=limit,
        offset=offset,
        has_more=offset + limit < int(total),
    )
