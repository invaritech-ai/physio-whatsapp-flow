"""Tests for standardized auth behavior on protected endpoints."""

from unittest.mock import patch

from sqlmodel import Session, select

from app.models import AccessRequest, Therapist, User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_admin_unknown_user_returns_access_pending_and_creates_request(
    client,
    db_session: Session,
):
    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": "unknown-admin-sub-1",
            "email": "unknown-admin@test.com",
        }
        response = client.get("/api/v1/admin/specialties", headers=_auth_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "access_pending"

    access_request = db_session.exec(
        select(AccessRequest).where(AccessRequest.neon_auth_sub == "unknown-admin-sub-1")
    ).first()
    assert access_request is not None
    assert access_request.status == "pending"


def test_admin_role_mismatch_returns_access_denied(client, db_session: Session):
    therapist_user = User(
        neon_auth_sub="therapist-sub-admin-route",
        email="therapist-route@test.com",
        display_name="Therapist Route",
        role="therapist",
        is_active=True,
    )
    db_session.add(therapist_user)
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": therapist_user.neon_auth_sub,
            "email": therapist_user.email,
        }
        response = client.get("/api/v1/admin/specialties", headers=_auth_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "access_denied"


def test_admin_inactive_user_returns_account_inactive(client, db_session: Session):
    inactive_admin = User(
        neon_auth_sub="inactive-admin-sub-1",
        email="inactive-admin@test.com",
        display_name="Inactive Admin",
        role="admin",
        is_active=False,
    )
    db_session.add(inactive_admin)
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": inactive_admin.neon_auth_sub,
            "email": inactive_admin.email,
        }
        response = client.get("/api/v1/admin/specialties", headers=_auth_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "account_inactive"


def test_therapist_sessions_inactive_profile_returns_account_inactive(
    client,
    db_session: Session,
):
    user = User(
        neon_auth_sub="inactive-therapist-profile-sub",
        email="inactive-therapist@test.com",
        display_name="Dr. Inactive Profile",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name="Dr. Inactive Profile",
        is_active=False,
    )
    db_session.add(therapist)
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": user.neon_auth_sub,
            "email": user.email,
        }
        response = client.get("/api/v1/sessions", headers=_auth_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "account_inactive"


def test_admin_rejected_access_request_returns_access_denied(client, db_session: Session):
    access_request = AccessRequest(
        neon_auth_sub="rejected-admin-sub-1",
        email="rejected-admin@test.com",
        status="rejected",
    )
    db_session.add(access_request)
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": "rejected-admin-sub-1",
            "email": "rejected-admin@test.com",
        }
        response = client.get("/api/v1/admin/specialties", headers=_auth_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "access_denied"
