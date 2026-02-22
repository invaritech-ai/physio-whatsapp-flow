"""Celery tasks for Calendly webhook event processing."""

from __future__ import annotations

import asyncio
from typing import Any

from app.worker import celery_app


@celery_app.task(
    name="tasks.process_calendly_webhook_event",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
)
def process_calendly_webhook_event(
    self,
    *,
    event_type: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Process a verified Calendly webhook event in the background."""
    from app.api.v1.routes.webhooks import process_calendly_event  # deferred import
    from app.db.session import get_session

    with next(get_session()) as db:
        return asyncio.run(process_calendly_event(db=db, event_type=event_type, payload=payload))
