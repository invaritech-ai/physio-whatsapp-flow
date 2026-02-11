"""Tests for admin auth-event listing endpoint."""

from datetime import datetime, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import AuthEvent, User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def test_admin_can_list_auth_events_with_filters(client, db_session: Session):
    admin = User(
        neon_auth_sub="auth-events-admin-sub",
        email="auth-events-admin@test.com",
        display_name="Auth Events Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    db_session.add(
        AuthEvent(
            event_type="denied_access",
            user_sub="unknown-sub-1",
            reason="access_request_pending",
            details_json='{"ip":"127.0.0.1"}',
        )
    )
    db_session.add(
        AuthEvent(
            event_type="role_change",
            user_id=42,
            actor_user_id=admin.id,
            reason="therapist->admin",
            details_json='{"previous_role":"therapist","new_role":"admin"}',
        )
    )
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        }
        response = client.get(
            "/api/v1/admin/auth-events?event_type=role_change",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["event_type"] == "role_change"
    assert data[0]["reason"] == "therapist->admin"
    assert data[0]["details"]["new_role"] == "admin"


def test_non_admin_cannot_list_auth_events(client, db_session: Session):
    therapist = User(
        neon_auth_sub="auth-events-therapist-sub",
        email="auth-events-therapist@test.com",
        display_name="Auth Events Therapist",
        role="therapist",
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": therapist.neon_auth_sub,
            "email": therapist.email,
        }
        response = client.get("/api/v1/admin/auth-events", headers=_auth_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "access_denied"
