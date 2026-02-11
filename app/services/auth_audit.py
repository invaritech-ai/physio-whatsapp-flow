"""Utilities for persisting auth audit events."""

from __future__ import annotations

from typing import Any
import json
import logging

from sqlmodel import Session

from app.models import AuthEvent

logger = logging.getLogger("app.auth")


def record_auth_event(
    db: Session,
    *,
    event_type: str,
    user_id: int | None = None,
    user_sub: str | None = None,
    actor_user_id: int | None = None,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
    commit: bool = False,
) -> AuthEvent | None:
    """Persist an auth event. Best-effort when commit=True."""
    details_json = None
    if details is not None:
        details_json = json.dumps(details, default=str)

    event = AuthEvent(
        event_type=event_type,
        user_id=user_id,
        user_sub=user_sub,
        actor_user_id=actor_user_id,
        reason=reason,
        details_json=details_json,
    )
    db.add(event)

    if not commit:
        return event

    try:
        db.commit()
        db.refresh(event)
        return event
    except Exception:
        db.rollback()
        logger.exception(
            "auth.audit.persist_failed",
            extra={
                "event_type": event_type,
                "user_id": user_id,
                "user_sub": user_sub,
                "actor_user_id": actor_user_id,
            },
        )
        return None
