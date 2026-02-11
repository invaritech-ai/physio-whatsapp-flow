"""Tests for GET /api/v1/me access state behavior."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session, select

from app.models import AccessRequest, User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_me_creates_pending_access_request_for_first_login(client, db_session: Session):
    """First login creates access request and returns pending."""
    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": "new-sub-123",
            "email": "new.user@test.com",
        }
        response = client.get("/api/v1/me", headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["email"] == "new.user@test.com"

    access_requests = db_session.exec(
        select(AccessRequest).where(AccessRequest.neon_auth_sub == "new-sub-123")
    ).all()
    assert len(access_requests) == 1
    assert access_requests[0].status == "pending"
    assert access_requests[0].email == "new.user@test.com"


def test_me_returns_existing_pending_without_duplicate(client, db_session: Session):
    """Existing pending request is reused instead of creating another."""
    access_request = AccessRequest(
        neon_auth_sub="pending-sub-123",
        email="pending@test.com",
        status="pending",
    )
    db_session.add(access_request)
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": "pending-sub-123",
            "email": "updated-email@test.com",
        }
        response = client.get("/api/v1/me", headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["email"] == "pending@test.com"

    access_requests = db_session.exec(
        select(AccessRequest).where(AccessRequest.neon_auth_sub == "pending-sub-123")
    ).all()
    assert len(access_requests) == 1


def test_me_returns_rejected_when_access_request_rejected(client, db_session: Session):
    """Rejected access request state is returned by /me."""
    access_request = AccessRequest(
        neon_auth_sub="rejected-sub-123",
        email="rejected@test.com",
        status="rejected",
    )
    db_session.add(access_request)
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": "rejected-sub-123",
            "email": "rejected@test.com",
        }
        response = client.get("/api/v1/me", headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"
    assert data["email"] == "rejected@test.com"


def test_me_returns_approved_when_user_exists(client, db_session: Session):
    """Approved user returns role and profile metadata."""
    user = User(
        neon_auth_sub="approved-sub-123",
        email="approved@test.com",
        display_name="Dr. Approved",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": "approved-sub-123",
            "email": "approved@test.com",
        }
        response = client.get("/api/v1/me", headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["role"] == "therapist"
    assert data["user_id"] == user.id
    assert data["email"] == "approved@test.com"
    assert data["display_name"] == "Dr. Approved"
    assert data["is_active"] is True


def test_me_returns_401_when_sessions_revoked(client, db_session: Session):
    """Revoked user gets 401 invalid_token from /me."""
    now = datetime.now(timezone.utc)
    user = User(
        neon_auth_sub="revoked-sub-123",
        email="revoked@test.com",
        display_name="Dr. Revoked",
        role="therapist",
        is_active=True,
        revoked_at=now,
    )
    db_session.add(user)
    db_session.commit()

    # Token issued BEFORE revocation → should be rejected
    token_iat = (now - timedelta(minutes=5)).timestamp()
    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": "revoked-sub-123",
            "email": "revoked@test.com",
            "iat": token_iat,
        }
        response = client.get("/api/v1/me", headers=_auth_headers())

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_me_allows_token_issued_after_revocation(client, db_session: Session):
    """Token issued after revocation is still valid (re-login scenario)."""
    revoked_at = datetime.now(timezone.utc) - timedelta(hours=1)
    user = User(
        neon_auth_sub="re-login-sub-123",
        email="relogin@test.com",
        display_name="Dr. Relogin",
        role="therapist",
        is_active=True,
        revoked_at=revoked_at,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    # Token issued AFTER revocation → should be accepted
    token_iat = (revoked_at + timedelta(minutes=5)).timestamp()
    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": "re-login-sub-123",
            "email": "relogin@test.com",
            "iat": token_iat,
        }
        response = client.get("/api/v1/me", headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["user_id"] == user.id
