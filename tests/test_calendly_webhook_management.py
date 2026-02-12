"""Tests for Calendly webhook check/registration management endpoints."""

from unittest.mock import patch

from sqlmodel import Session

from app.api.v1.routes.admin import therapists as admin_therapists_route
from app.api.v1.routes.therapist import onboarding as therapist_onboarding_route
from app.models import Therapist, User
from app.services.calendly_webhooks import REQUIRED_EVENTS


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _create_therapist(db_session: Session, sub: str, email: str) -> Therapist:
    user = User(
        neon_auth_sub=sub,
        email=email,
        display_name="Dr. Webhook",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name="Dr. Webhook",
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return therapist


def _create_admin(db_session: Session, sub: str, email: str) -> User:
    admin = User(
        neon_auth_sub=sub,
        email=email,
        display_name="Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def test_required_webhook_events_match_supported_subscription_events():
    assert REQUIRED_EVENTS == {"invitee.created", "invitee.canceled"}


def test_therapist_check_webhook_with_explicit_pat(client, db_session: Session):
    _create_therapist(db_session, "therapist-webhook-sub-1", "therapist1@test.com")

    with (
        patch("app.core.auth._verify_neon_token") as mock_verify,
        patch("app.api.v1.routes.therapist.onboarding.check_webhook_registration") as mock_check,
        patch.object(therapist_onboarding_route.settings, "public_base_url", "https://api.test.local"),
    ):
        mock_verify.return_value = {
            "sub": "therapist-webhook-sub-1",
            "email": "therapist1@test.com",
        }

        mock_check.return_value = {
            "user_uri": "https://api.calendly.com/users/U1",
            "organization_uri": "https://api.calendly.com/organizations/O1",
            "has_matching_webhook": True,
            "needs_registration": False,
            "missing_events": [],
            "subscriptions": [],
            "warnings": [],
        }

        response = client.post(
            "/api/v1/therapist/onboarding/calendly-webhook/check",
            json={"calendly_pat": "explicit_pat"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["endpoint_url"] == "https://api.test.local/api/v1/webhooks/calendly"
    assert data["has_matching_webhook"] is True
    mock_check.assert_called_once_with(
        "explicit_pat",
        "https://api.test.local/api/v1/webhooks/calendly",
    )


def test_therapist_register_webhook_uses_stored_pat(client, db_session: Session):
    therapist = _create_therapist(db_session, "therapist-webhook-sub-2", "therapist2@test.com")
    therapist.calendly_pat_encrypted = "encrypted_pat_blob"
    db_session.add(therapist)
    db_session.commit()

    with (
        patch("app.core.auth._verify_neon_token") as mock_verify,
        patch("app.api.v1.routes.therapist.onboarding.decrypt_string") as mock_decrypt,
        patch("app.api.v1.routes.therapist.onboarding.register_webhook_if_needed") as mock_register,
        patch.object(therapist_onboarding_route.settings, "public_base_url", "https://api.test.local"),
    ):
        mock_verify.return_value = {
            "sub": "therapist-webhook-sub-2",
            "email": "therapist2@test.com",
        }
        mock_decrypt.return_value = "stored_pat"
        mock_register.return_value = {
            "user_uri": "https://api.calendly.com/users/U2",
            "organization_uri": "https://api.calendly.com/organizations/O2",
            "has_matching_webhook": True,
            "needs_registration": False,
            "missing_events": [],
            "subscriptions": [],
            "warnings": [],
            "created": False,
            "created_webhook_uri": None,
            "signing_key": None,
        }

        response = client.post(
            "/api/v1/therapist/onboarding/calendly-webhook/register",
            json={},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["created"] is False
    mock_decrypt.assert_called_once_with("encrypted_pat_blob")
    mock_register.assert_called_once_with(
        "stored_pat",
        "https://api.test.local/api/v1/webhooks/calendly",
    )


def test_therapist_check_webhook_without_pat_returns_400(client, db_session: Session):
    _create_therapist(db_session, "therapist-webhook-sub-3", "therapist3@test.com")

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": "therapist-webhook-sub-3",
            "email": "therapist3@test.com",
        }
        response = client.post(
            "/api/v1/therapist/onboarding/calendly-webhook/check",
            json={},
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert "Calendly PAT not configured" in response.json()["detail"]


def test_admin_can_trigger_therapist_webhook_check(client, db_session: Session):
    _create_admin(db_session, "admin-webhook-sub-1", "admin@test.com")
    therapist = _create_therapist(db_session, "therapist-webhook-sub-4", "therapist4@test.com")
    therapist.calendly_pat_encrypted = "encrypted_pat_blob"
    db_session.add(therapist)
    db_session.commit()

    with (
        patch("app.core.auth._verify_neon_token") as mock_verify,
        patch("app.api.v1.routes.admin.therapists.decrypt_string") as mock_decrypt,
        patch("app.api.v1.routes.admin.therapists.check_webhook_registration") as mock_check,
        patch.object(admin_therapists_route.settings, "public_base_url", "https://api.test.local"),
    ):
        mock_verify.return_value = {
            "sub": "admin-webhook-sub-1",
            "email": "admin@test.com",
        }
        mock_decrypt.return_value = "stored_pat"
        mock_check.return_value = {
            "user_uri": "https://api.calendly.com/users/U4",
            "organization_uri": "https://api.calendly.com/organizations/O4",
            "has_matching_webhook": False,
            "needs_registration": True,
            "missing_events": ["invitee.canceled"],
            "subscriptions": [],
            "warnings": [],
        }

        response = client.post(
            f"/api/v1/admin/therapists/{therapist.id}/calendly-webhook/check",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["needs_registration"] is True
    assert data["endpoint_url"] == "https://api.test.local/api/v1/webhooks/calendly"
    mock_check.assert_called_once_with(
        "stored_pat",
        "https://api.test.local/api/v1/webhooks/calendly",
    )


def test_admin_webhook_check_requires_stored_pat(client, db_session: Session):
    _create_admin(db_session, "admin-webhook-sub-2", "admin2@test.com")
    therapist = _create_therapist(db_session, "therapist-webhook-sub-5", "therapist5@test.com")

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": "admin-webhook-sub-2",
            "email": "admin2@test.com",
        }
        response = client.post(
            f"/api/v1/admin/therapists/{therapist.id}/calendly-webhook/check",
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert "stored Calendly PAT" in response.json()["detail"]
