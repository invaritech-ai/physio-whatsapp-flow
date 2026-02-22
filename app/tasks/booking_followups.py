"""Celery tasks for booking-link follow-up nudges."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from sqlmodel import select

from app.models import Client, MessageLog
from app.models import Session as TherapySession
from app.services.bot.helpers import send_and_log
from app.services.timezone_utils import as_utc
from app.worker import celery_app


logger = logging.getLogger(__name__)
_BOOKING_LINK_MARKER = "Click the link below to choose your preferred time"
_STAGE_MARKERS = {
    1: "Gentle reminder:",
    2: "Friendly follow-up:",
}


def _parse_link_sent_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _has_booking_after_link(
    *,
    db,
    client_id: int,
    therapist_id: int | None,
    duration_minutes: int | None,
    link_sent_at: datetime,
) -> bool:
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
            return True
    return False


def _has_newer_booking_link(*, db, client_id: int, link_sent_at: datetime) -> bool:
    logs = db.exec(
        select(MessageLog).where(
            MessageLog.client_id == client_id,
            MessageLog.direction == "outbound",
        )
    ).all()
    for log in logs:
        if _BOOKING_LINK_MARKER not in log.body:
            continue
        if as_utc(log.created_at) > link_sent_at:
            return True
    return False


def _stage_already_sent(*, db, client_id: int, link_sent_at: datetime, stage: int) -> bool:
    marker = _STAGE_MARKERS.get(stage)
    if not marker:
        return False
    logs = db.exec(
        select(MessageLog).where(
            MessageLog.client_id == client_id,
            MessageLog.direction == "outbound",
        )
    ).all()
    for log in logs:
        if marker in log.body and as_utc(log.created_at) >= link_sent_at:
            return True
    return False


def _build_followup_message(stage: int, scheduling_url: str, therapist_name: str) -> str:
    if stage == 1:
        return (
            "Gentle reminder:\n\n"
            f"Your booking link with {therapist_name} is still active:\n"
            f"{scheduling_url}\n\n"
            "If you need help picking a time, reply to this chat."
        )
    return (
        "Friendly follow-up:\n\n"
        f"We can still help you confirm your session with {therapist_name}.\n"
        f"Complete booking here: {scheduling_url}\n\n"
        "Need assistance? Reply to this chat anytime."
    )


@celery_app.task(
    name="tasks.send_booking_link_followup",
    bind=True,
    max_retries=2,
    retry_backoff=True,
    retry_jitter=True,
)
def send_booking_link_followup(
    self,
    *,
    client_id: int,
    therapist_id: int | None,
    duration_minutes: int | None,
    therapist_name: str,
    scheduling_url: str,
    link_sent_at_iso: str,
    stage: int,
) -> dict:
    """Send a booking-link follow-up if no booking has been confirmed."""
    from app.db.session import get_session

    if stage not in _STAGE_MARKERS:
        return {"status": "ignored", "reason": "invalid_stage"}

    link_sent_at = _parse_link_sent_at(link_sent_at_iso)

    with next(get_session()) as db:
        client = db.get(Client, client_id)
        if not client:
            return {"status": "skipped", "reason": "client_not_found"}

        if _has_booking_after_link(
            db=db,
            client_id=client_id,
            therapist_id=therapist_id,
            duration_minutes=duration_minutes,
            link_sent_at=link_sent_at,
        ):
            return {"status": "skipped", "reason": "already_booked"}

        if _has_newer_booking_link(db=db, client_id=client_id, link_sent_at=link_sent_at):
            return {"status": "skipped", "reason": "stale_link"}

        if _stage_already_sent(
            db=db,
            client_id=client_id,
            link_sent_at=link_sent_at,
            stage=stage,
        ):
            return {"status": "skipped", "reason": "already_sent"}

        try:
            message = _build_followup_message(stage, scheduling_url, therapist_name)
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
            raise

