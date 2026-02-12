"""Tests for Calendly invitee.rescheduled webhook handling."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.api.v1.routes.webhooks import handle_invitee_rescheduled
from app.models import Client, Session as TherapySession, Therapist, TherapistEventType, User


def _as_utc(dt: datetime) -> datetime:
    """Normalize naive datetimes from SQLite to UTC-aware for comparisons."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _seed_therapist_client_and_session(db_session):
    user = User(
        neon_auth_sub="reschedule-therapist-sub",
        email="reschedule-therapist@test.com",
        display_name="Dr. Reschedule",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name="Dr. Reschedule",
        is_active=True,
        calendly_user_uri="https://api.calendly.com/users/RESCHED",
        calendly_pat_encrypted="encrypted_pat_blob",
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)

    client = Client(phone_e164="+85290000001", name="Test Client", conversation_state="IDLE")
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)

    old_start = datetime.now(timezone.utc) + timedelta(days=1)
    old_session = TherapySession(
        client_id=client.id,
        therapist_id=therapist.id,
        start_time=old_start,
        end_time=old_start + timedelta(minutes=30),
        duration_minutes=30,
        status="scheduled",
        source="calendly",
        calendly_event_uri="https://api.calendly.com/scheduled_events/OLD",
        calendly_invitee_uri="https://api.calendly.com/scheduled_events/OLD/invitees/OLDI",
    )
    db_session.add(old_session)
    db_session.commit()
    db_session.refresh(old_session)

    new_event_type = TherapistEventType(
        therapist_id=therapist.id,
        calendly_event_type_uri="https://api.calendly.com/event_types/45MIN",
        duration_minutes=45,
        scheduling_url="https://calendly.com/reschedule/45min",
        is_active=True,
    )
    db_session.add(new_event_type)
    db_session.commit()

    return therapist, client, old_session, new_event_type


@pytest.mark.anyio
async def test_rescheduled_updates_existing_session(db_session):
    therapist, _, old_session, new_event_type = _seed_therapist_client_and_session(db_session)

    payload = {
        "old_event": "https://api.calendly.com/scheduled_events/OLD",
        "new_event": "https://api.calendly.com/scheduled_events/NEW",
        "old_invitee": {"uri": "https://api.calendly.com/scheduled_events/OLD/invitees/OLDI"},
        "new_invitee": {"uri": "https://api.calendly.com/scheduled_events/NEW/invitees/NEWI"},
    }

    with (
        patch("app.api.v1.routes.webhooks.decrypt_string") as mock_decrypt,
        patch("app.api.v1.routes.webhooks.get_scheduled_event_with_pat") as mock_event,
    ):
        mock_decrypt.return_value = "plain_pat"
        mock_event.return_value = {
            "start_time": "2026-03-01T10:00:00Z",
            "end_time": "2026-03-01T10:45:00Z",
            "event_type": new_event_type.calendly_event_type_uri,
            "status": "active",
        }

        result = await handle_invitee_rescheduled(db_session, payload)

    assert result["status"] == "success"
    assert result["action"] == "rescheduled"
    assert result["session_id"] == old_session.id

    db_session.refresh(old_session)
    assert old_session.therapist_id == therapist.id
    assert old_session.calendly_event_uri == "https://api.calendly.com/scheduled_events/NEW"
    assert old_session.calendly_invitee_uri == "https://api.calendly.com/scheduled_events/NEW/invitees/NEWI"
    assert old_session.duration_minutes == 45
    assert old_session.status == "scheduled"
    assert _as_utc(old_session.start_time) == datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    assert _as_utc(old_session.end_time) == datetime(2026, 3, 1, 10, 45, tzinfo=timezone.utc)


@pytest.mark.anyio
async def test_rescheduled_merges_when_new_event_session_already_exists(db_session):
    _, client, old_session, new_event_type = _seed_therapist_client_and_session(db_session)

    # Simulate out-of-order webhooks: a session already exists for new event URI.
    new_start = datetime.now(timezone.utc) + timedelta(days=2)
    new_session = TherapySession(
        client_id=client.id,
        therapist_id=old_session.therapist_id,
        start_time=new_start,
        end_time=new_start + timedelta(minutes=45),
        duration_minutes=45,
        status="scheduled",
        source="calendly",
        calendly_event_uri="https://api.calendly.com/scheduled_events/NEW",
        calendly_invitee_uri="https://api.calendly.com/scheduled_events/NEW/invitees/NEWI",
    )
    db_session.add(new_session)
    db_session.commit()
    db_session.refresh(new_session)

    payload = {
        "old_event": "https://api.calendly.com/scheduled_events/OLD",
        "new_event": "https://api.calendly.com/scheduled_events/NEW",
        "old_invitee": {"uri": "https://api.calendly.com/scheduled_events/OLD/invitees/OLDI"},
        "new_invitee": {"uri": "https://api.calendly.com/scheduled_events/NEW/invitees/NEWI"},
    }

    with (
        patch("app.api.v1.routes.webhooks.decrypt_string") as mock_decrypt,
        patch("app.api.v1.routes.webhooks.get_scheduled_event_with_pat") as mock_event,
    ):
        mock_decrypt.return_value = "plain_pat"
        mock_event.return_value = {
            "start_time": "2026-03-02T11:00:00Z",
            "end_time": "2026-03-02T11:45:00Z",
            "event_type": new_event_type.calendly_event_type_uri,
            "status": "active",
        }

        result = await handle_invitee_rescheduled(db_session, payload)

    assert result["status"] == "success"
    assert result["action"] == "rescheduled"
    assert result["session_id"] == new_session.id

    db_session.refresh(old_session)
    db_session.refresh(new_session)
    assert old_session.status == "cancelled"
    assert new_session.status == "scheduled"
    assert new_session.duration_minutes == 45
    assert _as_utc(new_session.start_time) == datetime(2026, 3, 2, 11, 0, tzinfo=timezone.utc)
    assert _as_utc(new_session.end_time) == datetime(2026, 3, 2, 11, 45, tzinfo=timezone.utc)


@pytest.mark.anyio
async def test_rescheduled_returns_not_found_when_session_missing(db_session):
    payload = {
        "old_event": "https://api.calendly.com/scheduled_events/DOES_NOT_EXIST",
    }

    result = await handle_invitee_rescheduled(db_session, payload)

    assert result["status"] == "not_found"
