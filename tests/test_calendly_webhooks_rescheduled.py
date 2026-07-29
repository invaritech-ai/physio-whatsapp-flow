"""Tests for Calendly invitee.rescheduled webhook handling."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import select

from app.api.v1.routes.webhooks import (
    handle_invitee_canceled,
    handle_invitee_created,
    handle_invitee_rescheduled,
)
from app.models import AuthEvent, Client, Session as TherapySession, Therapist, TherapistEventType, User


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

    events = db_session.exec(
        select(AuthEvent).where(
            AuthEvent.user_id == therapist.user_id,
            AuthEvent.event_type == "therapist.notification.booking_rescheduled",
        )
    ).all()
    assert len(events) == 1
    assert events[0].reason == f"session:{old_session.id}:rescheduled"
    details = json.loads(events[0].details_json or "{}")
    assert details["session_id"] == old_session.id
    assert details["action"] == "rescheduled"


@pytest.mark.anyio
async def test_rescheduled_merges_when_new_event_session_already_exists(db_session):
    therapist, client, old_session, new_event_type = _seed_therapist_client_and_session(db_session)

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

    events = db_session.exec(
        select(AuthEvent).where(
            AuthEvent.user_id == therapist.user_id,
            AuthEvent.event_type == "therapist.notification.booking_rescheduled",
        )
    ).all()
    assert len(events) == 1
    assert events[0].reason == f"session:{new_session.id}:rescheduled"
    details = json.loads(events[0].details_json or "{}")
    assert details["session_id"] == new_session.id
    assert details["action"] == "rescheduled"


@pytest.mark.anyio
async def test_rescheduled_returns_not_found_when_session_missing(db_session):
    payload = {
        "old_event": "https://api.calendly.com/scheduled_events/DOES_NOT_EXIST",
    }

    result = await handle_invitee_rescheduled(db_session, payload)

    assert result["status"] == "not_found"


@pytest.mark.anyio
async def test_created_payload_with_reschedule_links_updates_old_session(db_session):
    therapist, _, old_session, new_event_type = _seed_therapist_client_and_session(db_session)

    payload = {
        "event": "https://api.calendly.com/scheduled_events/NEW",
        "invitee": {
            "uri": "https://api.calendly.com/scheduled_events/NEW/invitees/NEWI",
            "name": "Test Client",
        },
        "old_event": "https://api.calendly.com/scheduled_events/OLD",
        "old_invitee": {"uri": "https://api.calendly.com/scheduled_events/OLD/invitees/OLDI"},
        "rescheduled": True,
        "event_memberships": [{"user": therapist.calendly_user_uri}],
        "questions_and_answers": [{"question": "Phone Number", "answer": "+85290000001"}],
    }

    with (
        patch("app.api.v1.routes.webhooks.decrypt_string") as mock_decrypt,
        patch("app.api.v1.routes.webhooks.get_scheduled_event_with_pat") as mock_event,
    ):
        mock_decrypt.return_value = "plain_pat"
        mock_event.return_value = {
            "start_time": "2026-03-03T09:00:00Z",
            "end_time": "2026-03-03T09:45:00Z",
            "event_type": new_event_type.calendly_event_type_uri,
            "status": "active",
        }

        result = await handle_invitee_created(db_session, payload)

    assert result["status"] == "success"
    assert result["session_id"] == old_session.id

    db_session.refresh(old_session)
    assert old_session.calendly_event_uri == "https://api.calendly.com/scheduled_events/NEW"
    assert old_session.calendly_invitee_uri == "https://api.calendly.com/scheduled_events/NEW/invitees/NEWI"
    assert old_session.duration_minutes == 45
    assert old_session.status == "scheduled"
    assert _as_utc(old_session.start_time) == datetime(2026, 3, 3, 9, 0, tzinfo=timezone.utc)
    assert _as_utc(old_session.end_time) == datetime(2026, 3, 3, 9, 45, tzinfo=timezone.utc)


@pytest.mark.anyio
async def test_cancel_then_created_reschedule_flow_keeps_single_scheduled_session(db_session):
    therapist, _, old_session, new_event_type = _seed_therapist_client_and_session(db_session)

    cancel_payload = {
        "event": "https://api.calendly.com/scheduled_events/OLD",
        "invitee": {"uri": "https://api.calendly.com/scheduled_events/OLD/invitees/OLDI"},
        "rescheduled": True,
    }

    cancel_result = await handle_invitee_canceled(db_session, cancel_payload)
    assert cancel_result["status"] == "success"
    db_session.refresh(old_session)
    # The session is still parked as cancelled so out-of-order delivery stays
    # deterministic, but nobody is told it was cancelled — it was only moved.
    assert old_session.status == "cancelled"
    cancel_events = db_session.exec(
        select(AuthEvent).where(
            AuthEvent.user_id == therapist.user_id,
            AuthEvent.event_type == "therapist.notification.booking_cancelled",
        )
    ).all()
    assert cancel_events == []

    created_payload = {
        "event": "https://api.calendly.com/scheduled_events/NEW",
        "invitee": {
            "uri": "https://api.calendly.com/scheduled_events/NEW/invitees/NEWI",
            "name": "Test Client",
        },
        "old_event": "https://api.calendly.com/scheduled_events/OLD",
        "old_invitee": {"uri": "https://api.calendly.com/scheduled_events/OLD/invitees/OLDI"},
        "rescheduled": True,
        "event_memberships": [{"user": therapist.calendly_user_uri}],
        "questions_and_answers": [{"question": "Phone Number", "answer": "+85290000001"}],
    }

    with (
        patch("app.api.v1.routes.webhooks.decrypt_string") as mock_decrypt,
        patch("app.api.v1.routes.webhooks.get_scheduled_event_with_pat") as mock_event,
    ):
        mock_decrypt.return_value = "plain_pat"
        mock_event.return_value = {
            "start_time": "2026-03-04T12:00:00Z",
            "end_time": "2026-03-04T12:45:00Z",
            "event_type": new_event_type.calendly_event_type_uri,
            "status": "active",
        }

        created_result = await handle_invitee_created(db_session, created_payload)

    assert created_result["status"] == "success"
    assert created_result["session_id"] == old_session.id

    db_session.refresh(old_session)
    assert old_session.status == "scheduled"
    assert old_session.calendly_event_uri == "https://api.calendly.com/scheduled_events/NEW"
    assert old_session.calendly_invitee_uri == "https://api.calendly.com/scheduled_events/NEW/invitees/NEWI"
    assert _as_utc(old_session.start_time) == datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)

    # Still no cancellation notice, and the reschedule is announced exactly once —
    # on the therapist bell and on the admin operations queue.
    assert (
        db_session.exec(
            select(AuthEvent).where(
                AuthEvent.event_type == "therapist.notification.booking_cancelled",
            )
        ).all()
        == []
    )
    reschedule_events = db_session.exec(
        select(AuthEvent).where(
            AuthEvent.user_id == therapist.user_id,
            AuthEvent.event_type == "therapist.notification.booking_rescheduled",
        )
    ).all()
    assert len(reschedule_events) == 1
    assert reschedule_events[0].reason == f"session:{old_session.id}:rescheduled"

    admin_queue = db_session.exec(
        select(AuthEvent).where(
            AuthEvent.event_type == "admin.calendly.queue.invitee.rescheduled",
        )
    ).all()
    assert len(admin_queue) == 1
    assert admin_queue[0].reason == f"session:{old_session.id}:calendly:rescheduled"
    assert (
        db_session.exec(
            select(AuthEvent).where(
                AuthEvent.event_type == "admin.calendly.queue.invitee.canceled",
            )
        ).all()
        == []
    )
