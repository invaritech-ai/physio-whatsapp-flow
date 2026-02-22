"""Celery tasks for periodic data synchronization jobs."""

from __future__ import annotations

import logging

from sqlmodel import select

from app.models import Therapist
from app.services.therapist_onboarding import sync_event_types
from app.worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.sync_therapist_event_types",
    bind=True,
    max_retries=2,
    retry_backoff=True,
    retry_jitter=True,
)
def sync_therapist_event_types(self) -> dict[str, int]:
    """
    Periodically sync active therapist event types from Calendly.

    Intended to be triggered by Celery Beat every few hours.
    """
    from app.db.session import get_session  # deferred import

    total = 0
    succeeded = 0
    failed = 0

    with next(get_session()) as db:
        therapists = db.exec(
            select(Therapist).where(
                Therapist.is_active == True,  # noqa: E712
                Therapist.calendly_user_uri.is_not(None),  # type: ignore[attr-defined]
            )
        ).all()

        for therapist in therapists:
            total += 1
            try:
                _, errors = sync_event_types(db, therapist)
                if errors:
                    failed += 1
                    db.rollback()
                    logger.warning(
                        "celery.sync_event_types.failed therapist_id=%s errors=%s",
                        therapist.id,
                        errors,
                    )
                    continue

                db.commit()
                succeeded += 1
            except Exception:
                db.rollback()
                failed += 1
                logger.exception(
                    "celery.sync_event_types.exception therapist_id=%s",
                    therapist.id,
                )

    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
    }
