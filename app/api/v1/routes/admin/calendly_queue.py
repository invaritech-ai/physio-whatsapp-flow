"""Admin operational queue for Calendly workflow events."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.api.v1.schemas.calendly_ops import (
    CalendlyQueueItem,
    CalendlyQueueListResponse,
    CalendlyQueueTransitionResponse,
)
from app.core.auth import get_current_admin
from app.db.session import get_session
from app.models import AuthEvent, User

router = APIRouter(prefix="/admin/calendly/queue", tags=["Admin - Calendly"])

_QUEUE_EVENT_TYPE_MAP = {
    "admin.calendly.queue.invitee.created": "invitee.created",
    "admin.calendly.queue.invitee.canceled": "invitee.canceled",
    "admin.calendly.queue.invitee.rescheduled": "invitee.rescheduled",
}
_QUEUE_EVENT_TYPES = tuple(_QUEUE_EVENT_TYPE_MAP.keys())


def _load_details(row: AuthEvent) -> dict:
    if not row.details_json:
        return {}
    try:
        data = json.loads(row.details_json)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_dt(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _queue_status(details: dict) -> str:
    raw = details.get("queue_status")
    if raw in {"new", "acknowledged", "resolved"}:
        return raw
    return "new"


@router.get("", response_model=CalendlyQueueListResponse)
def list_calendly_queue(
    status: str | None = Query(default=None, pattern="^(new|acknowledged|resolved)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    rows = db.exec(
        select(AuthEvent)
        .where(AuthEvent.event_type.in_(_QUEUE_EVENT_TYPES))  # type: ignore[arg-type]
        .order_by(AuthEvent.created_at.desc(), AuthEvent.id.desc())
    ).all()

    items: list[CalendlyQueueItem] = []
    for row in rows:
        details = _load_details(row)
        row_status = _queue_status(details)
        if status and row_status != status:
            continue
        event_type = _QUEUE_EVENT_TYPE_MAP.get(row.event_type)
        if event_type is None:
            continue
        items.append(
            CalendlyQueueItem(
                id=row.id or 0,
                event_type=event_type,
                calendly_event_uri=details.get("calendly_event_uri"),
                calendly_invitee_uri=details.get("calendly_invitee_uri"),
                client_id=details.get("client_id"),
                client_name=details.get("client_name"),
                therapist_id=details.get("therapist_id"),
                therapist_name=details.get("therapist_name"),
                start_time=_parse_dt(details.get("start_time_utc")),
                end_time=_parse_dt(details.get("end_time_utc")),
                status=row_status,  # type: ignore[arg-type]
                created_at=row.created_at,
            )
        )

    total = len(items)
    page = items[offset : offset + limit]
    return CalendlyQueueListResponse(
        items=page,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )


def _transition_queue_item(
    *,
    item_id: int,
    target_status: str,
    db: Session,
) -> CalendlyQueueTransitionResponse:
    row = db.exec(
        select(AuthEvent).where(
            AuthEvent.id == item_id,
            AuthEvent.event_type.in_(_QUEUE_EVENT_TYPES),  # type: ignore[arg-type]
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="queue_item_not_found")

    details = _load_details(row)
    current_status = _queue_status(details)
    if current_status == "resolved":
        target_status = "resolved"

    now = datetime.now(timezone.utc)
    details["queue_status"] = target_status
    details["queue_updated_at"] = now.isoformat()
    row.reason = target_status
    row.details_json = json.dumps(details, default=str)
    db.add(row)
    db.commit()
    db.refresh(row)

    return CalendlyQueueTransitionResponse(
        id=row.id or 0,
        status=target_status,  # type: ignore[arg-type]
        updated_at=now,
    )


@router.post("/{item_id}/ack", response_model=CalendlyQueueTransitionResponse)
def acknowledge_calendly_queue_item(
    item_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    return _transition_queue_item(item_id=item_id, target_status="acknowledged", db=db)


@router.post("/{item_id}/resolve", response_model=CalendlyQueueTransitionResponse)
def resolve_calendly_queue_item(
    item_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    return _transition_queue_item(item_id=item_id, target_status="resolved", db=db)
