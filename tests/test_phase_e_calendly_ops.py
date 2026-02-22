"""Phase E tests for Calendly admin queue + therapist feed contracts."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.api.v1.routes.webhooks import handle_invitee_canceled, handle_invitee_created
from app.models import (
    AuthEvent,
    Client,
    Session as TherapySession,
    Therapist,
    TherapistEventType,
    User,
)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _create_admin(db_session: Session, suffix: str = "phase-e") -> User:
    admin = User(
        neon_auth_sub=f"{suffix}-admin-sub",
        email=f"{suffix}-admin@test.com",
        display_name="Phase E Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def _create_therapist(
    db_session: Session,
    *,
    suffix: str = "phase-e",
    calendly_user_uri: str = "https://api.calendly.com/users/PHASE_E",
) -> tuple[User, Therapist]:
    user = User(
        neon_auth_sub=f"{suffix}-therapist-sub",
        email=f"{suffix}-therapist@test.com",
        display_name="Dr Phase E",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name="Dr Phase E",
        is_active=True,
        preferred_timezone="Asia/Hong_Kong",
        calendly_user_uri=calendly_user_uri,
        calendly_pat_encrypted="encrypted-pat",
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return user, therapist


@contextmanager
def _auth_context(user: User):
    with patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": user.neon_auth_sub,
            "email": user.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    ):
        yield


def test_admin_calendly_queue_list_and_transitions(client, db_session: Session):
    admin = _create_admin(db_session, suffix="queue")
    created_at = datetime.now(timezone.utc) - timedelta(minutes=10)

    queue_new = AuthEvent(
        event_type="admin.calendly.queue.invitee.created",
        reason="session:101:calendly:created",
        details_json=json.dumps(
            {
                "session_id": 101,
                "calendly_event_uri": "https://api.calendly.com/scheduled_events/Q101",
                "calendly_invitee_uri": "https://api.calendly.com/scheduled_events/Q101/invitees/I101",
                "client_id": 201,
                "client_name": "Queue Client",
                "therapist_id": 301,
                "therapist_name": "Dr Queue",
                "start_time_utc": "2026-03-01T09:00:00+00:00",
                "end_time_utc": "2026-03-01T09:45:00+00:00",
                "queue_status": "new",
            }
        ),
        created_at=created_at,
    )
    queue_seen = AuthEvent(
        event_type="admin.calendly.queue.invitee.canceled",
        reason="session:102:calendly:canceled",
        details_json=json.dumps(
            {
                "session_id": 102,
                "client_id": 202,
                "client_name": "Queue Client 2",
                "therapist_id": 302,
                "therapist_name": "Dr Queue 2",
                "start_time_utc": "2026-03-02T09:00:00+00:00",
                "end_time_utc": "2026-03-02T09:45:00+00:00",
                "queue_status": "acknowledged",
            }
        ),
        created_at=created_at - timedelta(minutes=1),
    )
    db_session.add(queue_new)
    db_session.add(queue_seen)
    db_session.commit()
    db_session.refresh(queue_new)

    with _auth_context(admin):
        filtered = client.get(
            "/api/v1/admin/calendly/queue",
            params={"status": "new", "limit": 20, "offset": 0},
            headers=_auth_headers(),
        )
    assert filtered.status_code == 200
    payload = filtered.json()
    assert payload["total"] == 1
    assert payload["items"][0]["event_type"] == "invitee.created"
    assert payload["items"][0]["status"] == "new"

    with _auth_context(admin):
        ack = client.post(
            f"/api/v1/admin/calendly/queue/{queue_new.id}/ack",
            headers=_auth_headers(),
        )
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"

    with _auth_context(admin):
        resolved = client.post(
            f"/api/v1/admin/calendly/queue/{queue_new.id}/resolve",
            headers=_auth_headers(),
        )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    with _auth_context(admin):
        idempotent = client.post(
            f"/api/v1/admin/calendly/queue/{queue_new.id}/ack",
            headers=_auth_headers(),
        )
    assert idempotent.status_code == 200
    assert idempotent.json()["status"] == "resolved"


def test_therapist_calendly_feed_list_and_seen(client, db_session: Session):
    therapist_user, therapist = _create_therapist(db_session, suffix="feed")

    feed_new = AuthEvent(
        event_type="therapist.calendly.feed.created",
        user_id=therapist.user_id,
        reason="session:201:calendly:created",
        details_json=json.dumps(
            {
                "session_id": 201,
                "client_id": 401,
                "client_name": "Feed Client",
                "start_time_utc": "2026-03-03T09:00:00+00:00",
                "end_time_utc": "2026-03-03T09:45:00+00:00",
                "feed_status": "new",
            }
        ),
    )
    feed_seen = AuthEvent(
        event_type="therapist.calendly.feed.canceled",
        user_id=therapist.user_id,
        reason="session:202:calendly:canceled",
        details_json=json.dumps(
            {
                "session_id": 202,
                "client_id": 402,
                "client_name": "Feed Client 2",
                "start_time_utc": "2026-03-04T09:00:00+00:00",
                "end_time_utc": "2026-03-04T09:45:00+00:00",
                "feed_status": "seen",
            }
        ),
    )
    db_session.add(feed_new)
    db_session.add(feed_seen)
    db_session.commit()
    db_session.refresh(feed_new)

    with _auth_context(therapist_user):
        filtered = client.get(
            "/api/v1/therapist/calendly/feed",
            params={"status": "new", "limit": 20, "offset": 0},
            headers=_auth_headers(),
        )
    assert filtered.status_code == 200
    payload = filtered.json()
    assert payload["total"] == 1
    assert payload["items"][0]["event_type"] == "created"
    assert payload["items"][0]["status"] == "new"

    with _auth_context(therapist_user):
        seen = client.patch(
            f"/api/v1/therapist/calendly/feed/{feed_new.id}/seen",
            headers=_auth_headers(),
        )
    assert seen.status_code == 200
    assert seen.json()["status"] == "seen"


@pytest.mark.anyio
async def test_invitee_webhooks_append_phase_e_operational_events(db_session: Session):
    therapist_user, therapist = _create_therapist(db_session, suffix="webhook")

    client_row = Client(
        phone_e164="+85295550088",
        name="Operational Client",
        conversation_state="IDLE",
    )
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    event_type = TherapistEventType(
        therapist_id=therapist.id,
        calendly_event_type_uri="https://api.calendly.com/event_types/OPS_45",
        duration_minutes=45,
        scheduling_url="https://calendly.com/dr-phase-e/45min",
        is_active=True,
    )
    db_session.add(event_type)
    db_session.commit()

    created_payload = {
        "scheduled_event": {
            "uri": "https://api.calendly.com/scheduled_events/OPS_EVENT_1",
            "event_memberships": [{"user": therapist.calendly_user_uri}],
        },
        "event": "https://api.calendly.com/scheduled_events/OPS_EVENT_1",
        "invitee": {
            "uri": "https://api.calendly.com/scheduled_events/OPS_EVENT_1/invitees/OPS_INV_1",
            "name": "Operational Client",
        },
        "questions_and_answers": [
            {"question": "Phone Number", "answer": "+85295550088"},
        ],
    }

    with (
        patch("app.api.v1.routes.webhooks.decrypt_string", return_value="plain-pat"),
        patch(
            "app.api.v1.routes.webhooks.get_scheduled_event_with_pat",
            return_value={
                "start_time": "2026-03-05T09:00:00Z",
                "end_time": "2026-03-05T09:45:00Z",
                "event_type": event_type.calendly_event_type_uri,
                "status": "active",
            },
        ),
        patch("app.api.v1.routes.webhooks.send_and_log", return_value="SM-OPS-1"),
    ):
        created_result = await handle_invitee_created(db_session, created_payload)
    assert created_result["status"] == "success"

    session_row = db_session.exec(select(TherapySession)).first()
    assert session_row is not None

    canceled_payload = {
        "event": "https://api.calendly.com/scheduled_events/OPS_EVENT_1",
        "invitee": {"uri": "https://api.calendly.com/scheduled_events/OPS_EVENT_1/invitees/OPS_INV_1"},
    }
    canceled_result = await handle_invitee_canceled(db_session, canceled_payload)
    assert canceled_result["status"] == "success"

    admin_events = db_session.exec(
        select(AuthEvent)
        .where(AuthEvent.event_type.like("admin.calendly.queue.%"))
        .order_by(AuthEvent.id.asc())
    ).all()
    therapist_feed_events = db_session.exec(
        select(AuthEvent)
        .where(
            AuthEvent.event_type.like("therapist.calendly.feed.%"),
            AuthEvent.user_id == therapist_user.id,
        )
        .order_by(AuthEvent.id.asc())
    ).all()

    assert {row.event_type for row in admin_events} >= {
        "admin.calendly.queue.invitee.created",
        "admin.calendly.queue.invitee.canceled",
    }
    assert {row.event_type for row in therapist_feed_events} >= {
        "therapist.calendly.feed.created",
        "therapist.calendly.feed.canceled",
    }

    created_admin = next(
        row for row in admin_events if row.event_type == "admin.calendly.queue.invitee.created"
    )
    created_feed = next(
        row for row in therapist_feed_events if row.event_type == "therapist.calendly.feed.created"
    )

    admin_details = json.loads(created_admin.details_json or "{}")
    feed_details = json.loads(created_feed.details_json or "{}")
    assert admin_details.get("queue_status") == "new"
    assert admin_details.get("session_id") == session_row.id
    assert feed_details.get("feed_status") == "new"
    assert feed_details.get("session_id") == session_row.id
