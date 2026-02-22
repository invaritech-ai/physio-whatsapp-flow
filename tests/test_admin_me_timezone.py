"""Tests for admin timezone self-service endpoints."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.models import User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


@pytest.fixture(name="admin_headers")
def admin_headers_fixture(db_session: Session):
    admin_user = User(
        neon_auth_sub="admin-timezone-sub",
        email="admin-timezone@test.com",
        display_name="Admin Timezone",
        role="admin",
        is_active=True,
    )
    db_session.add(admin_user)
    db_session.commit()

    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": admin_user.neon_auth_sub,
            "email": admin_user.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        }
        yield _auth_headers()


def test_get_admin_timezone_defaults_to_null(client, admin_headers):
    response = client.get("/api/v1/admin/me/timezone", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"preferred_timezone": None}


def test_update_admin_timezone_success(client, db_session: Session, admin_headers):
    response = client.patch(
        "/api/v1/admin/me/timezone",
        json={"preferred_timezone": " Asia/Hong_Kong "},
        headers=admin_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["preferred_timezone"] == "Asia/Hong_Kong"
    assert data["message"] == "Preferred timezone updated successfully"

    user = db_session.exec(
        select(User).where(User.email == "admin-timezone@test.com")
    ).first()
    assert user is not None
    assert user.preferred_timezone == "Asia/Hong_Kong"


def test_update_admin_timezone_rejects_invalid_value(client, admin_headers):
    response = client.patch(
        "/api/v1/admin/me/timezone",
        json={"preferred_timezone": "Mars/Olympus"},
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_preferred_timezone"
