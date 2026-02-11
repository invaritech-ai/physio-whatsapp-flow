"""Tests for persisted auth audit events."""

from datetime import datetime, timezone
from unittest.mock import patch

from sqlmodel import Session, select

from app.models import AuthEvent, User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def test_denied_access_persists_auth_event(client, db_session: Session):
    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": "audit-unknown-sub",
            "email": "audit-unknown@test.com",
        }
        response = client.get("/api/v1/admin/specialties", headers=_auth_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "access_pending"

    event = db_session.exec(
        select(AuthEvent)
        .where(AuthEvent.user_sub == "audit-unknown-sub")
        .where(AuthEvent.event_type == "denied_access")
    ).first()
    assert event is not None
    assert event.reason == "access_request_pending"


def test_role_change_persists_role_and_revoke_events(client, db_session: Session):
    actor_admin = User(
        neon_auth_sub="audit-role-actor-sub",
        email="audit-role-actor@test.com",
        display_name="Audit Role Actor",
        role="admin",
        is_active=True,
    )
    target_user = User(
        neon_auth_sub="audit-role-target-sub",
        email="audit-role-target@test.com",
        display_name="Audit Role Target",
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

    events = db_session.exec(
        select(AuthEvent).where(AuthEvent.user_id == target_user.id)
    ).all()
    event_types = {e.event_type for e in events}
    assert "revoke" in event_types
    assert "role_change" in event_types

    role_event = next(e for e in events if e.event_type == "role_change")
    assert role_event.actor_user_id == actor_admin.id
    assert role_event.reason == "therapist->admin"


def test_status_change_persists_status_and_revoke_events(client, db_session: Session):
    actor_admin = User(
        neon_auth_sub="audit-status-actor-sub",
        email="audit-status-actor@test.com",
        display_name="Audit Status Actor",
        role="admin",
        is_active=True,
    )
    target_user = User(
        neon_auth_sub="audit-status-target-sub",
        email="audit-status-target@test.com",
        display_name="Audit Status Target",
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

    events = db_session.exec(
        select(AuthEvent).where(AuthEvent.user_id == target_user.id)
    ).all()
    event_types = {e.event_type for e in events}
    assert "revoke" in event_types
    assert "account_status_change" in event_types

    status_event = next(e for e in events if e.event_type == "account_status_change")
    assert status_event.actor_user_id == actor_admin.id
    assert status_event.reason == "True->False"
