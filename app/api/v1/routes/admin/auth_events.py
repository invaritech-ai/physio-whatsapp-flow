"""Admin endpoints for auth audit events."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.api.v1.schemas.auth_event import AuthEventResponse
from app.core.auth import get_current_admin
from app.db.session import get_session
from app.models import AuthEvent, User

router = APIRouter(prefix="/admin/auth-events", tags=["Admin - Auth Events"])


@router.get("", response_model=list[AuthEventResponse])
def list_auth_events(
    event_type: str | None = None,
    user_id: int | None = None,
    actor_user_id: int | None = None,
    reason: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """List auth events with optional filters and pagination."""
    _ = admin
    query = select(AuthEvent).order_by(AuthEvent.created_at.desc()).offset(offset).limit(limit)

    if event_type:
        query = query.where(AuthEvent.event_type == event_type)
    if user_id is not None:
        query = query.where(AuthEvent.user_id == user_id)
    if actor_user_id is not None:
        query = query.where(AuthEvent.actor_user_id == actor_user_id)
    if reason:
        query = query.where(AuthEvent.reason == reason)

    rows = db.exec(query).all()
    response: list[AuthEventResponse] = []
    for row in rows:
        details = None
        if row.details_json:
            try:
                parsed = json.loads(row.details_json)
                if isinstance(parsed, dict):
                    details = parsed
            except json.JSONDecodeError:
                details = None

        response.append(
            AuthEventResponse(
                id=row.id,
                event_type=row.event_type,
                user_id=row.user_id,
                user_sub=row.user_sub,
                actor_user_id=row.actor_user_id,
                reason=row.reason,
                details=details,
                created_at=row.created_at,
            )
        )

    return response
