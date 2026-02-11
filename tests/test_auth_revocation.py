"""Tests for auth token revocation via user.revoked_at."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def test_revoked_user_rejects_older_token(client, db_session: Session):
    revoked_at = datetime.now(timezone.utc)
    admin = User(
        neon_auth_sub="revoked-admin-sub",
        email="revoked-admin@test.com",
        display_name="Revoked Admin",
        role="admin",
        is_active=True,
        revoked_at=revoked_at,
    )
    db_session.add(admin)
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(revoked_at - timedelta(minutes=5)),
        }
        response = client.get("/api/v1/admin/specialties", headers=_auth_headers())

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_revoked_user_accepts_newer_token(client, db_session: Session):
    revoked_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    admin = User(
        neon_auth_sub="active-after-revoke-sub",
        email="active-after-revoke@test.com",
        display_name="Active After Revoke",
        role="admin",
        is_active=True,
        revoked_at=revoked_at,
    )
    db_session.add(admin)
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(revoked_at + timedelta(minutes=1)),
        }
        response = client.get("/api/v1/admin/specialties", headers=_auth_headers())

    assert response.status_code == 200


def test_role_change_revokes_target_user_sessions(client, db_session: Session):
    actor_admin = User(
        neon_auth_sub="actor-admin-sub",
        email="actor-admin@test.com",
        display_name="Actor Admin",
        role="admin",
        is_active=True,
    )
    target_user = User(
        neon_auth_sub="target-user-sub",
        email="target-user@test.com",
        display_name="Target User",
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
            f"/api/v1/admin/users/{target_user.id}/role",
            json={"role": "admin"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200

    db_session.refresh(target_user)
    assert target_user.revoked_at is not None
