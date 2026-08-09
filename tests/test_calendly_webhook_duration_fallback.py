"""Tests for the defensive duration fallback in invitee.created handling.

Reproduces the 2026-06-05 incident: a brand-new booking arrives for a Calendly
event type that was never mapped in therapisteventtype (e.g. a duplicate-named
"Movement" event created by an external booking tool). Previously the handler
dropped the booking ("Ambiguous event type mapping"); now it must fall back to
the duration Calendly reported and still save the session.
"""

from datetime import datetime, timezone

import pytest
from sqlmodel import select

from app.api.v1.routes.webhooks import handle_invitee_created
from app.models import Client, Session as TherapySession, Therapist, TherapistEventType, User


def _seed_therapist(db_session):
    user = User(
        neon_auth_sub="fallback-therapist-sub",
        email="fallback-therapist@test.com",
        display_name="Dr. Fallback",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name="Dr. Fallback",
        is_active=True,
        calendly_user_uri="https://api.calendly.com/users/FALLBACK",
        calendly_pat_encrypted="encrypted_pat_blob",
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return therapist


@pytest.mark.anyio
async def test_unmapped_event_type_falls_back_to_calendly_duration(db_session):
    """No mapping, no booking intent, no existing session -> use Calendly's 30 min."""
    therapist = _seed_therapist(db_session)

    # Note: deliberately NO TherapistEventType row for this event type.
    unmapped_event_type = "https://api.calendly.com/event_types/UNMAPPED-DUPLICATE"

    payload = {
        "event": "https://api.calendly.com/scheduled_events/NEW",
        "uri": "https://api.calendly.com/scheduled_events/NEW/invitees/NEWI",
        "name": "Yiwen Wu",
        "event_memberships": [{"user": therapist.calendly_user_uri}],
        "questions_and_answers": [
            {"question": "Your WhatsApp number to link.", "answer": "+85267679639"}
        ],
    }

    from unittest.mock import patch

    with (
        patch("app.api.v1.routes.webhooks.decrypt_string", return_value="plain_pat"),
        patch(
            "app.api.v1.routes.webhooks.get_scheduled_event_with_pat",
            return_value={
                "start_time": "2026-06-07T01:00:00Z",
                "end_time": "2026-06-07T01:30:00Z",  # 30 minutes
                "event_type": unmapped_event_type,
                "status": "active",
            },
        ),
    ):
        result = await handle_invitee_created(db_session, payload)

    assert result["status"] == "success"

    session = db_session.get(TherapySession, result["session_id"])
    assert session is not None
    assert session.duration_minutes == 30  # fell back to Calendly's reported length
    assert session.calendly_event_uri == "https://api.calendly.com/scheduled_events/NEW"
    assert session.status == "scheduled"

    client = db_session.get(Client, result["client_id"])
    assert client is not None
    assert client.phone_e164 == "+85267679639"


@pytest.mark.anyio
async def test_single_mapping_still_wins_over_calendly_duration(db_session):
    """A real mapping must still take priority over the raw Calendly duration."""
    therapist = _seed_therapist(db_session)

    event_type_uri = "https://api.calendly.com/event_types/MAPPED-45"
    db_session.add(
        TherapistEventType(
            therapist_id=therapist.id,
            calendly_event_type_uri=event_type_uri,
            duration_minutes=45,
            scheduling_url="https://calendly.com/fallback/45min",
            is_active=True,
        )
    )
    db_session.commit()

    payload = {
        "event": "https://api.calendly.com/scheduled_events/MAP",
        "uri": "https://api.calendly.com/scheduled_events/MAP/invitees/MAPI",
        "name": "Mapped Client",
        "event_memberships": [{"user": therapist.calendly_user_uri}],
        "questions_and_answers": [
            {"question": "Your WhatsApp number to link.", "answer": "+85211112222"}
        ],
    }

    from unittest.mock import patch

    with (
        patch("app.api.v1.routes.webhooks.decrypt_string", return_value="plain_pat"),
        patch(
            "app.api.v1.routes.webhooks.get_scheduled_event_with_pat",
            return_value={
                # Calendly reports 30, but the mapping says 45 -> mapping wins.
                "start_time": "2026-06-07T02:00:00Z",
                "end_time": "2026-06-07T02:30:00Z",
                "event_type": event_type_uri,
                "status": "active",
            },
        ),
    ):
        result = await handle_invitee_created(db_session, payload)

    assert result["status"] == "success"
    session = db_session.get(TherapySession, result["session_id"])
    assert session.duration_minutes == 45
