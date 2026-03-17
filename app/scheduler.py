"""In-process APScheduler jobs replacing Celery beat + worker.

Periodic syncs run on fixed intervals.  Booking follow-ups are one-shot
delayed jobs scheduled via ``schedule_booking_followup()``.
"""

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

logger = logging.getLogger(__name__)

AVAILABILITY_CACHE_EVENT_TYPE = "system.calendly.availability.cache"
TIME_BAND_WEEKDAY_DAY = "weekday_day"
TIME_BAND_WEEKDAY_EVENING = "weekday_evening"
TIME_BAND_WEEKEND = "weekend"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    try:
        return ZoneInfo(_therapist_zone_name(therapist))
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _cache_reason(therapist_id: int, duration_minutes: int) -> str:
    return f"therapist:{therapist_id}:duration:{duration_minutes}"


# ---------------------------------------------------------------------------
# Periodic sync: therapist event types
# ---------------------------------------------------------------------------

def run_sync_therapist_event_types() -> dict[str, int]:
    """Sync active therapist event types from Calendly."""
    from app.db.session import get_session

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
                        "sync_event_types.failed therapist_id=%s errors=%s",
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
                    "sync_event_types.exception therapist_id=%s",
                    therapist.id,
                )

    result = {"total": total, "succeeded": succeeded, "failed": failed}
    logger.info("sync_therapist_event_types completed: %s", result)
    return result


# ---------------------------------------------------------------------------
# Periodic sync: therapist availability
# ---------------------------------------------------------------------------

def run_sync_therapist_availability() -> dict[str, int]:
    """Snapshot therapist availability buckets from Calendly."""
    from app.db.session import get_session

    now = datetime.now(timezone.utc)
    window_start = now + timedelta(minutes=5)
    window_end = window_start + timedelta(days=7)
    expires_at = now + timedelta(minutes=settings.availability_cache_ttl_minutes)

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
                    "sync_therapist_availability.exception therapist_id=%s",
                    therapist.id,
                )

    result = {
        "therapists_total": therapists_total,
        "therapists_succeeded": therapists_succeeded,
        "therapists_failed": therapists_failed,
        "durations_synced": durations_synced,
        "slots_total": slots_total,
    }
    logger.info("sync_therapist_availability completed: %s", result)
    return result


# ---------------------------------------------------------------------------
# Booking follow-up (delayed one-shot jobs)
# ---------------------------------------------------------------------------

def _run_booking_followup(
    *,
    client_id: int,
    therapist_id: int | None,
    duration_minutes: int | None,
    therapist_name: str,
    scheduling_url: str,
    link_sent_at_iso: str,
    stage: int,
) -> dict:
    """Execute a single booking follow-up check + send."""
    from app.db.session import get_session
    from app.models import Client, MessageLog
    from app.models import Session as TherapySession
    from app.services.bot.helpers import send_and_log
    from app.services.timezone_utils import as_utc

    BOOKING_LINK_MARKER = "Click the link below to choose your preferred time"
    STAGE_MARKERS = {1: "Gentle reminder:", 2: "Friendly follow-up:"}

    if stage not in STAGE_MARKERS:
        return {"status": "ignored", "reason": "invalid_stage"}

    parsed = datetime.fromisoformat(link_sent_at_iso)
    link_sent_at = parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    with next(get_session()) as db:
        client = db.get(Client, client_id)
        if not client:
            return {"status": "skipped", "reason": "client_not_found"}

        # Check if already booked
        sessions = db.exec(
            select(TherapySession).where(
                TherapySession.client_id == client_id,
                TherapySession.source == "calendly",
                TherapySession.status.in_(["scheduled", "started", "completed"]),  # type: ignore[attr-defined]
            )
        ).all()
        for session in sessions:
            if therapist_id is not None and session.therapist_id != therapist_id:
                continue
            if duration_minutes is not None and session.duration_minutes != duration_minutes:
                continue
            if as_utc(session.created_at) >= link_sent_at:
                return {"status": "skipped", "reason": "already_booked"}

        # Check for newer booking link
        logs = db.exec(
            select(MessageLog).where(
                MessageLog.client_id == client_id,
                MessageLog.direction == "outbound",
            )
        ).all()
        for log in logs:
            if BOOKING_LINK_MARKER in log.body and as_utc(log.created_at) > link_sent_at:
                return {"status": "skipped", "reason": "stale_link"}

        # Check if stage already sent
        marker = STAGE_MARKERS[stage]
        for log in logs:
            if marker in log.body and as_utc(log.created_at) >= link_sent_at:
                return {"status": "skipped", "reason": "already_sent"}

        # Send
        if stage == 1:
            message = (
                "Gentle reminder:\n\n"
                f"Your booking link with {therapist_name} is still active:\n"
                f"{scheduling_url}\n\n"
                "If you need help picking a time, reply to this chat."
            )
        else:
            message = (
                "Friendly follow-up:\n\n"
                f"We can still help you confirm your session with {therapist_name}.\n"
                f"Complete booking here: {scheduling_url}\n\n"
                "Need assistance? Reply to this chat anytime."
            )

        try:
            send_and_log(
                db=db,
                phone_e164=client.phone_e164,
                body=message,
                client_id=client.id,
            )
            return {"status": "sent", "stage": stage, "client_id": client_id}
        except Exception:
            logger.exception(
                "Failed to send booking follow-up client_id=%s stage=%s",
                client_id,
                stage,
            )
            return {"status": "error", "stage": stage, "client_id": client_id}


def schedule_booking_followup(
    *,
    client_id: int,
    therapist_id: int,
    duration_minutes: int,
    therapist_name: str,
    scheduling_url: str,
    link_sent_at_iso: str,
    stage: int,
    delay_seconds: int,
) -> None:
    """Schedule a one-shot booking follow-up via the global APScheduler instance."""
    from app.main import scheduler

    run_date = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
    job_id = f"booking-followup-{client_id}-stage{stage}-{link_sent_at_iso}"

    scheduler.add_job(
        _run_booking_followup,
        "date",
        run_date=run_date,
        id=job_id,
        replace_existing=True,
        kwargs={
            "client_id": client_id,
            "therapist_id": therapist_id,
            "duration_minutes": duration_minutes,
            "therapist_name": therapist_name,
            "scheduling_url": scheduling_url,
            "link_sent_at_iso": link_sent_at_iso,
            "stage": stage,
        },
    )
    logger.info(
        "Scheduled booking follow-up client_id=%s stage=%s in %ss",
        client_id,
        stage,
        delay_seconds,
    )
