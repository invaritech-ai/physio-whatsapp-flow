"""Celery tasks for periodic data synchronization jobs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlmodel import select

from app.core.config import settings
from app.core.encryption import decrypt_string
from app.models import AuthEvent, Therapist, TherapistEventType
from app.services.calendly import get_event_type_available_times_with_pat
from app.services.therapist_onboarding import sync_event_types
from app.worker import celery_app

logger = logging.getLogger(__name__)
AVAILABILITY_CACHE_EVENT_TYPE = "system.calendly.availability.cache"
TIME_BAND_WEEKDAY_DAY = "weekday_day"
TIME_BAND_WEEKDAY_EVENING = "weekday_evening"
TIME_BAND_WEEKEND = "weekend"


def _bucket_for_local_time(local_start: datetime) -> str | None:
    weekday = local_start.weekday()
    hour = local_start.hour
    if weekday >= 5:
        return TIME_BAND_WEEKEND
    if 9 <= hour < 17:
        return TIME_BAND_WEEKDAY_DAY
    if hour >= 17:
        return TIME_BAND_WEEKDAY_EVENING
    return None


def _therapist_zone_name(therapist: Therapist) -> str:
    return therapist.preferred_timezone or settings.invoice_timezone or "UTC"


def _therapist_zone(therapist: Therapist) -> ZoneInfo:
    tz_name = _therapist_zone_name(therapist)
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _cache_reason(therapist_id: int, duration_minutes: int) -> str:
    return f"therapist:{therapist_id}:duration:{duration_minutes}"


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


@celery_app.task(
    name="tasks.sync_therapist_availability",
    bind=True,
    max_retries=2,
    retry_backoff=True,
    retry_jitter=True,
)
def sync_therapist_availability(self) -> dict[str, int]:
    """Periodically snapshot therapist availability buckets from Calendly."""
    from app.db.session import get_session  # deferred import

    now = datetime.now(timezone.utc)
    window_start = now + timedelta(minutes=5)
    window_end = window_start + timedelta(days=7)
    expires_at = now + timedelta(minutes=settings.celery_availability_cache_ttl_minutes)

    therapists_total = 0
    therapists_succeeded = 0
    therapists_failed = 0
    durations_synced = 0
    slots_total = 0

    with next(get_session()) as db:
        therapists = db.exec(
            select(Therapist).where(
                Therapist.is_active == True,  # noqa: E712
                Therapist.calendly_user_uri.is_not(None),  # type: ignore[attr-defined]
            )
        ).all()

        for therapist in therapists:
            therapists_total += 1
            if not therapist.id or not therapist.calendly_pat_encrypted:
                continue

            event_types = db.exec(
                select(TherapistEventType).where(
                    TherapistEventType.therapist_id == therapist.id,
                    TherapistEventType.is_active == True,  # noqa: E712
                )
            ).all()
            if not event_types:
                continue

            try:
                calendly_pat = decrypt_string(therapist.calendly_pat_encrypted)
                zone = _therapist_zone(therapist)
                timezone_name = _therapist_zone_name(therapist)

                for event_type in event_types:
                    slots = get_event_type_available_times_with_pat(
                        event_type_uri=event_type.calendly_event_type_uri,
                        calendly_pat=calendly_pat,
                        start_time=window_start,
                        end_time=window_end,
                    )

                    bucket_counts = {
                        TIME_BAND_WEEKDAY_DAY: 0,
                        TIME_BAND_WEEKDAY_EVENING: 0,
                        TIME_BAND_WEEKEND: 0,
                    }

                    for slot in slots:
                        if not isinstance(slot, dict):
                            continue
                        raw_start = slot.get("start_time")
                        if not isinstance(raw_start, str):
                            continue
                        try:
                            utc_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
                        except ValueError:
                            continue
                        if utc_start.tzinfo is None:
                            utc_start = utc_start.replace(tzinfo=timezone.utc)
                        local_start = utc_start.astimezone(zone)
                        bucket = _bucket_for_local_time(local_start)
                        if bucket:
                            bucket_counts[bucket] += 1

                    has_buckets = {k: v > 0 for k, v in bucket_counts.items()}
                    details = {
                        "therapist_id": therapist.id,
                        "duration_minutes": event_type.duration_minutes,
                        "event_type_uri": event_type.calendly_event_type_uri,
                        "scheduling_url": event_type.scheduling_url,
                        "window_start_utc": window_start.isoformat(),
                        "window_end_utc": window_end.isoformat(),
                        "generated_at": now.isoformat(),
                        "expires_at": expires_at.isoformat(),
                        "timezone": timezone_name,
                        "slot_count": len([s for s in slots if isinstance(s, dict)]),
                        "bucket_counts": bucket_counts,
                        "has_buckets": has_buckets,
                    }

                    reason = _cache_reason(therapist.id, event_type.duration_minutes)
                    row = db.exec(
                        select(AuthEvent).where(
                            AuthEvent.event_type == AVAILABILITY_CACHE_EVENT_TYPE,
                            AuthEvent.reason == reason,
                        )
                    ).first()
                    if row:
                        row.user_id = therapist.user_id
                        row.details_json = json.dumps(details, default=str)
                        db.add(row)
                    else:
                        db.add(
                            AuthEvent(
                                event_type=AVAILABILITY_CACHE_EVENT_TYPE,
                                user_id=therapist.user_id,
                                reason=reason,
                                details_json=json.dumps(details, default=str),
                            )
                        )

                    durations_synced += 1
                    slots_total += details["slot_count"]

                db.commit()
                therapists_succeeded += 1
            except Exception:
                db.rollback()
                therapists_failed += 1
                logger.exception(
                    "celery.sync_therapist_availability.exception therapist_id=%s",
                    therapist.id,
                )

    return {
        "therapists_total": therapists_total,
        "therapists_succeeded": therapists_succeeded,
        "therapists_failed": therapists_failed,
        "durations_synced": durations_synced,
        "slots_total": slots_total,
    }
