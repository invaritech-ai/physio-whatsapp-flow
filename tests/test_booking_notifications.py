"""Tests for booking confirmation notifications."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import select

from app.api.v1.routes.webhooks import handle_invitee_created
from app.core.auth import get_current_therapist
from app.main import app
from app.models import BookingIntent, AuthEvent, Client, Session as TherapySession, Therapist, TherapistEventType, User


def _seed_therapist_and_client(db_session):
    user = User(
        neon_auth_sub="booking-notify-therapist-sub",
        email="booking-notify-therapist@test.com",
        display_name="Dr. Notify",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name="Dr. Notify",
        is_active=True,
        preferred_timezone="Asia/Hong_Kong",
        calendly_user_uri="https://api.calendly.com/users/BOOKING_NOTIFY",
        calendly_pat_encrypted="encrypted-pat",
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)

    client = Client(phone_e164="+85295550001", name="Client Notify", conversation_state="IDLE")
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)

    event_type = TherapistEventType(
        therapist_id=therapist.id,
        calendly_event_type_uri="https://api.calendly.com/event_types/BOOKING_NOTIFY_45",
        duration_minutes=45,
        scheduling_url="https://calendly.com/dr-notify/45min",
        is_active=True,
    )
    db_session.add(event_type)
    db_session.commit()
    return therapist, client, event_type


def _invitee_created_payload(therapist: Therapist) -> dict:
    return {
        "scheduled_event": {
            "uri": "https://api.calendly.com/scheduled_events/BOOKING_NOTIFY_EVENT",
            "event_memberships": [{"user": therapist.calendly_user_uri}],
        },
        "event": "https://api.calendly.com/scheduled_events/BOOKING_NOTIFY_EVENT",
        "invitee": {
            "uri": "https://api.calendly.com/scheduled_events/BOOKING_NOTIFY_EVENT/invitees/INVITEE1",
            "name": "Client Notify",
        },
        "questions_and_answers": [
            {"question": "Phone Number", "answer": "+85295550001"},
        ],
    }


@pytest.mark.anyio
async def test_invitee_created_sends_client_and_therapist_notifications(db_session):
    therapist, client, event_type = _seed_therapist_and_client(db_session)
    payload = _invitee_created_payload(therapist)

    with (
        patch("app.api.v1.routes.webhooks.decrypt_string", return_value="plain-pat"),
        patch(
            "app.api.v1.routes.webhooks.get_scheduled_event_with_pat",
            return_value={
                "start_time": "2026-03-10T09:00:00Z",
                "end_time": "2026-03-10T09:45:00Z",
                "event_type": event_type.calendly_event_type_uri,
                "status": "active",
            },
        ),
        patch("app.api.v1.routes.webhooks.send_and_log", return_value="SM-CONFIRM-1") as mock_send,
    ):
        result = await handle_invitee_created(db_session, payload)

    assert result["status"] == "success"
    assert mock_send.call_count == 1

    session_row = db_session.exec(select(TherapySession)).first()
    assert session_row is not None
    assert session_row.client_id == client.id
    assert session_row.therapist_id == therapist.id
    assert session_row.reminder_sent is True
    assert session_row.therapist_notified is True

    events = db_session.exec(
        select(AuthEvent).where(
            AuthEvent.user_id == therapist.user_id,
            AuthEvent.event_type == "therapist.notification.booking_confirmed",
        )
    ).all()
    assert len(events) == 1


@pytest.mark.anyio
async def test_invitee_created_notification_is_idempotent(db_session):
    therapist, _client, event_type = _seed_therapist_and_client(db_session)
    payload = _invitee_created_payload(therapist)

    with (
        patch("app.api.v1.routes.webhooks.decrypt_string", return_value="plain-pat"),
        patch(
            "app.api.v1.routes.webhooks.get_scheduled_event_with_pat",
            return_value={
                "start_time": "2026-03-10T09:00:00Z",
                "end_time": "2026-03-10T09:45:00Z",
                "event_type": event_type.calendly_event_type_uri,
                "status": "active",
            },
        ),
        patch("app.api.v1.routes.webhooks.send_and_log", return_value="SM-CONFIRM-1") as mock_send,
    ):
        first = await handle_invitee_created(db_session, payload)
        second = await handle_invitee_created(db_session, payload)

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert mock_send.call_count == 1
    events = db_session.exec(
        select(AuthEvent).where(
            AuthEvent.user_id == therapist.user_id,
            AuthEvent.event_type == "therapist.notification.booking_confirmed",
        )
    ).all()
    assert len(events) == 1


@pytest.mark.anyio
async def test_invitee_created_prefers_booking_intent_for_shared_uri(db_session):
    therapist, client, event_type = _seed_therapist_and_client(db_session)
    shared_uri = "https://api.calendly.com/event_types/BOOKING_NOTIFY_SHARED"
    event_type.calendly_event_type_uri = shared_uri
    event_type.scheduling_url = "https://calendly.com/dr-notify/shared"
    db_session.add(event_type)
    db_session.add(
        TherapistEventType(
            therapist_id=therapist.id,
            calendly_event_type_uri=shared_uri,
            duration_minutes=30,
            scheduling_url="https://calendly.com/dr-notify/shared",
            is_active=True,
        )
    )
    intent = BookingIntent(
        therapist_id=therapist.id,
        client_id=client.id,
        client_phone_e164=client.phone_e164,
        duration_minutes=30,
        calendly_event_type_uri=shared_uri,
        scheduling_url="https://calendly.com/dr-notify/shared",
        source="web",
    )
    db_session.add(intent)
    db_session.commit()
    db_session.refresh(intent)

    payload = _invitee_created_payload(therapist)

    with (
        patch("app.api.v1.routes.webhooks.decrypt_string", return_value="plain-pat"),
        patch(
            "app.api.v1.routes.webhooks.get_scheduled_event_with_pat",
            return_value={
                "start_time": "2026-03-10T09:00:00Z",
                "end_time": "2026-03-10T09:45:00Z",
                "event_type": shared_uri,
                "status": "active",
            },
        ),
        patch("app.api.v1.routes.webhooks.send_and_log", return_value="SM-CONFIRM-1"),
    ):
        result = await handle_invitee_created(db_session, payload)

    assert result["status"] == "success"

    session_row = db_session.exec(
        select(TherapySession).where(
            TherapySession.calendly_event_uri == "https://api.calendly.com/scheduled_events/BOOKING_NOTIFY_EVENT"
        )
    ).first()
    assert session_row is not None
    assert session_row.duration_minutes == 30

    db_session.refresh(intent)
    assert intent.consumed_at is not None


def test_therapist_notifications_endpoint_returns_feed(client, db_session):
    therapist, _client, _event_type = _seed_therapist_and_client(db_session)
    now = datetime.now(timezone.utc)
    event = AuthEvent(
        event_type="therapist.notification.booking_confirmed",
        user_id=therapist.user_id,
        reason="booking_confirmed",
        details_json=(
            '{"session_id": 123, "client_name": "Client Notify", '
            '"therapist_name": "Dr. Notify", "start_time_local": "Tue, Mar 10, 2026 5:00 PM"}'
        ),
        created_at=now - timedelta(minutes=5),
    )
    db_session.add(event)
    db_session.commit()

    app.dependency_overrides[get_current_therapist] = lambda: therapist
    try:
        response = client.get("/api/v1/therapist/notifications?limit=20&offset=0")
    finally:
        app.dependency_overrides.pop(get_current_therapist, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["event_type"] == "therapist.notification.booking_confirmed"
    assert "booking" in payload["items"][0]["title"].lower()
