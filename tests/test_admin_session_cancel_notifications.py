"""Admin-initiated cancellation raises the same notifications Calendly does (req 2.9)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session, select

from app.models import AuthEvent, Client, Session as TherapySession, Therapist, User


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _admin_auth_context(admin: User):
    return patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    )


def _seed(db_session: Session) -> tuple[User, TherapySession]:
    admin = User(
        neon_auth_sub="admin-cancel-notify-sub",
        email="admin-cancel-notify@test.com",
        display_name="Admin Cancel Notify",
        role="admin",
        is_active=True,
    )
    therapist_user = User(
        neon_auth_sub="therapist-cancel-notify-sub",
        email="therapist-cancel-notify@test.com",
        display_name="Dr Cancel Notify",
        role="therapist",
        is_active=True,
    )
    db_session.add(admin)
    db_session.add(therapist_user)
    db_session.commit()
    db_session.refresh(admin)
    db_session.refresh(therapist_user)

    therapist = Therapist(
        user_id=therapist_user.id,
        display_name=therapist_user.display_name,
        license_number="PT-CANCEL-1",
        is_active=True,
    )
    client = Client(phone_e164="+85298760011", name="Cancel Notify Client")
    db_session.add(therapist)
    db_session.add(client)
    db_session.commit()
    db_session.refresh(therapist)
    db_session.refresh(client)

    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
        tzinfo=None, microsecond=0
    )
    session_row = TherapySession(
        client_id=client.id,
        therapist_id=therapist.id,
        start_time=start,
        end_time=start + timedelta(minutes=45),
        duration_minutes=45,
        status="scheduled",
        source="manual",
        currency="HKD",
    )
    db_session.add(session_row)
    db_session.commit()
    db_session.refresh(session_row)
    return admin, session_row


def _events(db_session: Session, event_type: str, session_id: int) -> list[AuthEvent]:
    return list(
        db_session.exec(
            select(AuthEvent).where(
                AuthEvent.event_type == event_type,
                AuthEvent.reason.like(f"session:{session_id}:%"),  # type: ignore[union-attr]
            )
        ).all()
    )


def test_admin_cancel_raises_therapist_and_admin_queue_notifications(client, db_session):
    admin, session_row = _seed(db_session)

    with _admin_auth_context(admin):
        response = client.put(
            f"/api/v1/admin/sessions/{session_row.id}",
            json={"status": "cancelled"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"

    # Therapist bell.
    bell = _events(db_session, "therapist.notification.booking_cancelled", session_row.id)
    assert len(bell) == 1
    assert bell[0].reason == f"session:{session_row.id}:cancelled"

    # Admin operations queue — the row the Notifications page and bell count read.
    queue = _events(db_session, "admin.calendly.queue.invitee.canceled", session_row.id)
    assert len(queue) == 1
    assert queue[0].reason == f"session:{session_row.id}:calendly:canceled"
    assert '"queue_status": "new"' in (queue[0].details_json or "")


def test_admin_cancel_is_idempotent_and_silent_for_other_statuses(client, db_session):
    admin, session_row = _seed(db_session)
    queue_type = "admin.calendly.queue.invitee.canceled"

    with _admin_auth_context(admin):
        headers = {"Authorization": "Bearer test-token"}
        url = f"/api/v1/admin/sessions/{session_row.id}"

        # A non-cancel transition notifies nothing.
        assert client.put(url, json={"status": "completed"}, headers=headers).status_code == 200
        assert _events(db_session, queue_type, session_row.id) == []

        assert client.put(url, json={"status": "cancelled"}, headers=headers).status_code == 200
        assert len(_events(db_session, queue_type, session_row.id)) == 1

        # Re-selecting "cancelled" must not stack a second notification.
        assert client.put(url, json={"status": "cancelled"}, headers=headers).status_code == 200
        assert len(_events(db_session, queue_type, session_row.id)) == 1
