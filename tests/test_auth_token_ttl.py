"""Tests for optional access-token TTL policy enforcement."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.core.config import settings
from app.models import User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _admin_user(db_session: Session, *, sub: str, email: str) -> User:
    user = User(
        neon_auth_sub=sub,
        email=email,
        display_name="TTL Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_ttl_policy_disabled_allows_missing_exp_claim(client, db_session: Session):
    admin = _admin_user(db_session, sub="ttl-disabled-admin-sub", email="ttl-disabled@test.com")
    with (
        patch.object(settings, "auth_enforce_access_ttl", False),
        patch("app.core.auth._verify_neon_token") as mock_verify,
    ):
        mock_verify.return_value = {
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        }
        response = client.get("/api/v1/admin/specialties", headers=_auth_headers())

    assert response.status_code == 200


def test_ttl_policy_enabled_allows_short_lived_token(client, db_session: Session):
    admin = _admin_user(db_session, sub="ttl-short-admin-sub", email="ttl-short@test.com")
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=5)

    with (
        patch.object(settings, "auth_enforce_access_ttl", True),
        patch.object(settings, "auth_max_access_token_ttl_seconds", 600),
        patch("app.core.auth._verify_neon_token") as mock_verify,
    ):
        mock_verify.return_value = {
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(issued_at),
            "exp": _epoch(expires_at),
        }
        response = client.get("/api/v1/admin/specialties", headers=_auth_headers())

    assert response.status_code == 200


def test_ttl_policy_enabled_rejects_over_limit_token(client, db_session: Session):
    admin = _admin_user(db_session, sub="ttl-long-admin-sub", email="ttl-long@test.com")
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=30)

    with (
        patch.object(settings, "auth_enforce_access_ttl", True),
        patch.object(settings, "auth_max_access_token_ttl_seconds", 600),
        patch("app.core.auth._verify_neon_token") as mock_verify,
    ):
        mock_verify.return_value = {
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(issued_at),
            "exp": _epoch(expires_at),
        }
        response = client.get("/api/v1/admin/specialties", headers=_auth_headers())

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"
