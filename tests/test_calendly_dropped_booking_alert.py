"""Tests for the dropped-booking alert.

A verified Calendly webhook that does not result in a saved session must raise a
persisted admin alert (AuthEvent type 'admin.calendly.dropped_booking') so silent
data loss can no longer go unnoticed. Success cases must NOT raise an alert.
"""

import json

import pytest
from sqlmodel import select

from app.api.v1.routes.webhooks import process_calendly_event
from app.models import AuthEvent, Therapist, TherapistEventType, User


def _seed_therapist(db_session):
    user = User(
        neon_auth_sub="alert-therapist-sub",
        email="alert-therapist@test.com",
        display_name="Dr. Alert",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name="Dr. Alert",
        is_active=True,
        calendly_user_uri="https://api.calendly.com/users/ALERT",
        # Deliberately NO calendly_pat_encrypted -> handler fails with "missing_pat".
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return therapist


def _dropped_alerts(db_session):
    return db_session.exec(
        select(AuthEvent).where(
            AuthEvent.event_type == "admin.calendly.dropped_booking"
        )
    ).all()


@pytest.mark.anyio
async def test_dropped_booking_raises_alert(db_session):
    """A created event that fails (therapist has no PAT) must persist an alert."""
    therapist = _seed_therapist(db_session)

    payload = {
        "event": "https://api.calendly.com/scheduled_events/DROP",
        "uri": "https://api.calendly.com/scheduled_events/DROP/invitees/DROPI",
        "name": "Dropped Patient",
        "scheduled_event": {
            "uri": "https://api.calendly.com/scheduled_events/DROP",
            "event_memberships": [{"user": therapist.calendly_user_uri}],
        },
        "event_memberships": [{"user": therapist.calendly_user_uri}],
        "questions_and_answers": [
            {"question": "Your WhatsApp number to link.", "answer": "+85267679639"}
        ],
    }

    result = await process_calendly_event(
        db=db_session, event_type="invitee.created", payload=payload
    )
    assert result["status"] == "error"

    alerts = _dropped_alerts(db_session)
    assert len(alerts) == 1
    details = json.loads(alerts[0].details_json)
    assert details["webhook_event_type"] == "invitee.created"
    assert details["result_status"] == "error"
    assert details["calendly_invitee_uri"] == (
        "https://api.calendly.com/scheduled_events/DROP/invitees/DROPI"
    )
    assert details["invitee_name"] == "Dropped Patient"


@pytest.mark.anyio
async def test_dropped_booking_alert_is_idempotent(db_session):
    """Calendly retrying the same failed booking must not create duplicate alerts."""
    therapist = _seed_therapist(db_session)
    payload = {
        "event": "https://api.calendly.com/scheduled_events/DROP",
        "uri": "https://api.calendly.com/scheduled_events/DROP/invitees/DROPI",
        "name": "Dropped Patient",
        "scheduled_event": {
            "uri": "https://api.calendly.com/scheduled_events/DROP",
            "event_memberships": [{"user": therapist.calendly_user_uri}],
        },
        "event_memberships": [{"user": therapist.calendly_user_uri}],
        "questions_and_answers": [
            {"question": "Your WhatsApp number to link.", "answer": "+85267679639"}
        ],
    }

    await process_calendly_event(db=db_session, event_type="invitee.created", payload=payload)
    await process_calendly_event(db=db_session, event_type="invitee.created", payload=payload)

    assert len(_dropped_alerts(db_session)) == 1


@pytest.mark.anyio
async def test_successful_booking_does_not_raise_alert(db_session):
    """A booking that saves must not produce a dropped-booking alert."""
    from unittest.mock import patch

    user = User(
        neon_auth_sub="ok-therapist-sub",
        email="ok-therapist@test.com",
        display_name="Dr. OK",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    therapist = Therapist(
        user_id=user.id,
        display_name="Dr. OK",
        is_active=True,
        calendly_user_uri="https://api.calendly.com/users/OK",
        calendly_pat_encrypted="encrypted_pat_blob",
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    db_session.add(
        TherapistEventType(
            therapist_id=therapist.id,
            calendly_event_type_uri="https://api.calendly.com/event_types/OK45",
            duration_minutes=45,
            scheduling_url="https://calendly.com/ok/45min",
            is_active=True,
        )
    )
    db_session.commit()

    payload = {
        "event": "https://api.calendly.com/scheduled_events/OK",
        "uri": "https://api.calendly.com/scheduled_events/OK/invitees/OKI",
        "name": "Happy Patient",
        "scheduled_event": {
            "uri": "https://api.calendly.com/scheduled_events/OK",
            "event_memberships": [{"user": therapist.calendly_user_uri}],
        },
        "event_memberships": [{"user": therapist.calendly_user_uri}],
        "questions_and_answers": [
            {"question": "Your WhatsApp number to link.", "answer": "+85211112222"}
        ],
    }

    with (
        patch("app.api.v1.routes.webhooks.decrypt_string", return_value="plain_pat"),
        patch(
            "app.api.v1.routes.webhooks.get_scheduled_event_with_pat",
            return_value={
                "start_time": "2026-06-07T03:00:00Z",
                "end_time": "2026-06-07T03:45:00Z",
                "event_type": "https://api.calendly.com/event_types/OK45",
                "status": "active",
            },
        ),
    ):
        result = await process_calendly_event(
            db=db_session, event_type="invitee.created", payload=payload
        )

    assert result["status"] == "success"
    assert _dropped_alerts(db_session) == []
