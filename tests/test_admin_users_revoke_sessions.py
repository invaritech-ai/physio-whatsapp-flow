"""Tests for admin manual session revocation endpoint."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session, select

from app.models import AuthEvent, User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def test_admin_can_manually_revoke_user_sessions(client, db_session: Session):
    actor_admin = User(
        neon_auth_sub="manual-revoke-actor-admin-sub",
        email="manual-revoke-actor@test.com",
        display_name="Manual Revoke Actor",
        role="admin",
        is_active=True,
    )
    previous_revoked_at = datetime.now(timezone.utc) - timedelta(hours=1)
    target_user = User(
        neon_auth_sub="manual-revoke-target-sub",
        email="manual-revoke-target@test.com",
        display_name="Manual Revoke Target",
        role="therapist",
        is_active=True,
        revoked_at=previous_revoked_at,
    )
    db_session.add(actor_admin)
    db_session.add(target_user)
    db_session.commit()
    db_session.refresh(target_user)

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": actor_admin.neon_auth_sub,
            "email": actor_admin.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        }
        response = client.post(
            f"/api/v1/admin/users/{target_user.id}/revoke-sessions",
            json={"reason": "security incident"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == target_user.id
    assert data["email"] == target_user.email
    assert "revoked" in data["message"].lower()

    db_session.refresh(target_user)
    assert _as_utc(target_user.revoked_at) > _as_utc(previous_revoked_at)

    events = db_session.exec(
        select(AuthEvent).where(AuthEvent.user_id == target_user.id)
    ).all()
    event_types = {event.event_type for event in events}
    assert "revoke" in event_types
    assert "manual_revoke" in event_types


def test_non_admin_cannot_manually_revoke_sessions(client, db_session: Session):
    therapist_user = User(
        neon_auth_sub="manual-revoke-therapist-sub",
        email="manual-revoke-therapist@test.com",
        display_name="Manual Revoke Therapist",
        role="therapist",
        is_active=True,
    )
    db_session.add(therapist_user)
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": therapist_user.neon_auth_sub,
            "email": therapist_user.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        }
        response = client.post(
            "/api/v1/admin/users/999/revoke-sessions",
            json={},
            headers=_auth_headers(),
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "access_denied"


def test_manual_revoke_returns_404_for_unknown_user(client, db_session: Session):
    actor_admin = User(
        neon_auth_sub="manual-revoke-404-admin-sub",
        email="manual-revoke-404-admin@test.com",
        display_name="Manual Revoke 404 Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(actor_admin)
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": actor_admin.neon_auth_sub,
            "email": actor_admin.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        }
        response = client.post(
            "/api/v1/admin/users/987654/revoke-sessions",
            json={},
            headers=_auth_headers(),
        )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
