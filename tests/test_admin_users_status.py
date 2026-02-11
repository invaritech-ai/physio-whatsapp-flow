"""Tests for admin user status update endpoint."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def test_suspend_user_revokes_sessions(client, db_session: Session):
    actor_admin = User(
        neon_auth_sub="status-actor-admin-sub",
        email="status-actor-admin@test.com",
        display_name="Status Actor Admin",
        role="admin",
        is_active=True,
    )
    target_user = User(
        neon_auth_sub="status-target-user-sub",
        email="status-target@test.com",
        display_name="Status Target",
        role="therapist",
        is_active=True,
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
        response = client.patch(
            f"/api/v1/admin/users/{target_user.id}/status",
            json={"is_active": False},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["previous_is_active"] is True
    assert data["new_is_active"] is False
    assert "suspended" in data["message"].lower()

    db_session.refresh(target_user)
    assert target_user.is_active is False
    assert target_user.revoked_at is not None


def test_reactivate_user_revokes_old_tokens_again(client, db_session: Session):
    prior_revoked_at = datetime.now(timezone.utc) - timedelta(days=1)
    actor_admin = User(
        neon_auth_sub="reactivate-actor-admin-sub",
        email="reactivate-actor-admin@test.com",
        display_name="Reactivate Actor Admin",
        role="admin",
        is_active=True,
    )
    target_user = User(
        neon_auth_sub="reactivate-target-sub",
        email="reactivate-target@test.com",
        display_name="Reactivate Target",
        role="therapist",
        is_active=False,
        revoked_at=prior_revoked_at,
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
        response = client.patch(
            f"/api/v1/admin/users/{target_user.id}/status",
            json={"is_active": True},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["previous_is_active"] is False
    assert data["new_is_active"] is True
    assert "reactivated" in data["message"].lower()

    db_session.refresh(target_user)
    assert target_user.is_active is True
    assert target_user.revoked_at is not None
    assert _as_utc(target_user.revoked_at) > _as_utc(prior_revoked_at)


def test_cannot_deactivate_last_active_admin(client, db_session: Session):
    last_admin = User(
        neon_auth_sub="last-admin-sub",
        email="last-admin@test.com",
        display_name="Last Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(last_admin)
    db_session.commit()
    db_session.refresh(last_admin)

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": last_admin.neon_auth_sub,
            "email": last_admin.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        }
        response = client.patch(
            f"/api/v1/admin/users/{last_admin.id}/status",
            json={"is_active": False},
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert "last active admin" in response.json()["detail"].lower()
