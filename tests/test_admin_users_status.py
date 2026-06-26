"""Tests for admin user status update endpoint."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import Therapist, User


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


def test_bot_only_suspension_keeps_login_and_only_unbooks(
    client, db_session: Session, monkeypatch, tmp_path
):
    """Suspending a bot-only account removes it from the WhatsApp bot
    (therapist.is_active=False) but keeps login intact: user.is_active stays
    True and sessions are not revoked."""
    from app.core.config import settings

    emails_file = tmp_path / "bot_only_suspend_emails.txt"
    emails_file.write_text("avishek.alex15@gmail.com\n", encoding="utf-8")
    monkeypatch.setattr(settings, "bot_only_suspend_emails_file", str(emails_file))

    actor_admin = User(
        neon_auth_sub="bot-only-actor-admin-sub",
        email="bot-only-actor-admin@test.com",
        display_name="Bot Only Actor Admin",
        role="admin",
        is_active=True,
    )
    target_user = User(
        neon_auth_sub="bot-only-target-sub",
        email="avishek.alex15@gmail.com",
        display_name="Bot Only Target",
        role="therapist",
        is_active=True,
    )
    db_session.add(actor_admin)
    db_session.add(target_user)
    db_session.commit()
    db_session.refresh(target_user)

    therapist = Therapist(
        user_id=target_user.id,
        display_name=target_user.display_name,
        is_active=True,
        calendly_user_uri="https://api.calendly.com/users/bot-only-target",
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)

    # Suspend -> only removes from the bot.
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
    # Login stays active; response reflects the real (unchanged) user state.
    assert data["new_is_active"] is True
    assert "whatsapp bot" in data["message"].lower()

    db_session.refresh(target_user)
    db_session.refresh(therapist)
    assert target_user.is_active is True  # login retained
    assert target_user.revoked_at is None  # sessions NOT revoked
    assert therapist.is_active is False  # removed from the bot

    # Reactivate -> restores them to the bot.
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
    db_session.refresh(target_user)
    db_session.refresh(therapist)
    assert target_user.is_active is True
    assert therapist.is_active is True


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
