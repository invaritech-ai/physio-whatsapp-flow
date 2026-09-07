"""Therapist Calendly feed endpoints (new/seen workflow items)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.api.v1.schemas.calendly_ops import (
    TherapistCalendlyFeedItem,
    TherapistCalendlyFeedListResponse,
    TherapistCalendlyFeedSeenResponse,
)
from app.core.auth import get_current_therapist
from app.db.session import get_session
from app.models import AuthEvent, Therapist

router = APIRouter(prefix="/therapist/calendly/feed", tags=["Therapist - Calendly"])

_FEED_EVENT_TYPE_MAP = {
    "therapist.calendly.feed.created": "created",
    "therapist.calendly.feed.canceled": "canceled",
    "therapist.calendly.feed.rescheduled": "rescheduled",
}
_FEED_EVENT_TYPES = tuple(_FEED_EVENT_TYPE_MAP.keys())


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


def _feed_status(details: dict) -> str:
    raw = details.get("feed_status")
    if raw in {"new", "seen"}:
        return raw
    return "new"


@router.get("", response_model=TherapistCalendlyFeedListResponse)
def list_therapist_calendly_feed(
    status: str | None = Query(default=None, pattern="^(new|seen)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
):
    rows = db.exec(
        select(AuthEvent)
        .where(
            AuthEvent.user_id == therapist.user_id,
            AuthEvent.event_type.in_(_FEED_EVENT_TYPES),  # type: ignore[arg-type]
        )
        .order_by(AuthEvent.created_at.desc(), AuthEvent.id.desc())
    ).all()

    items: list[TherapistCalendlyFeedItem] = []
    for row in rows:
        details = _load_details(row)
        row_status = _feed_status(details)
        if status and row_status != status:
            continue
        event_type = _FEED_EVENT_TYPE_MAP.get(row.event_type)
        if event_type is None:
            continue
        items.append(
            TherapistCalendlyFeedItem(
                id=row.id or 0,
                event_type=event_type,  # type: ignore[arg-type]
                session_id=details.get("session_id"),
                client_id=details.get("client_id"),
                client_name=details.get("client_name"),
                start_time=_parse_dt(details.get("start_time_utc")),
                end_time=_parse_dt(details.get("end_time_utc")),
                status=row_status,  # type: ignore[arg-type]
                created_at=row.created_at,
            )
        )

    total = len(items)
    page = items[offset : offset + limit]
    return TherapistCalendlyFeedListResponse(
        items=page,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )


@router.patch("/{item_id}/seen", response_model=TherapistCalendlyFeedSeenResponse)
def mark_calendly_feed_item_seen(
    item_id: int,
    therapist: Therapist = Depends(get_current_therapist),
    db: Session = Depends(get_session),
):
    row = db.exec(
        select(AuthEvent).where(
            AuthEvent.id == item_id,
            AuthEvent.user_id == therapist.user_id,
            AuthEvent.event_type.in_(_FEED_EVENT_TYPES),  # type: ignore[arg-type]
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="feed_item_not_found")

    now = datetime.now(timezone.utc)
    details = _load_details(row)
    details["feed_status"] = "seen"
    details["seen_at"] = now.isoformat()
    row.details_json = json.dumps(details, default=str)
    # Status lives in details["feed_status"] only — `reason` is the append-side dedupe
    # key (session:<id>:calendly:<action>) and must survive being marked seen.
    db.add(row)
    db.commit()
    db.refresh(row)

    return TherapistCalendlyFeedSeenResponse(
        id=row.id or 0,
        status="seen",
        updated_at=now,
    )
