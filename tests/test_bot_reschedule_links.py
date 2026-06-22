"""Tests for client-facing reschedule/cancel links in bot flows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models import Client, Session as TherapySession, Therapist, User
from app.services.bot.menus import build_reschedule_menu
from app.services.bot.reschedule import get_upcoming_sessions_with_links


def _seed_client_session(db_session, hours_ahead: int = 48):
    user = User(
        neon_auth_sub="reschedule-links-therapist-sub",
        email="reschedule-links-therapist@test.com",
        display_name="Dr. Links",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name="Dr. Links",
        is_active=True,
        calendly_pat_encrypted="encrypted-pat",
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)

    client = Client(
        phone_e164="+85297770001",
        name="Client Links",
        conversation_state="IDLE",
    )
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)

    start_time = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    session = TherapySession(
        client_id=client.id,
        therapist_id=therapist.id,
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        status="scheduled",
        source="calendly",
        calendly_event_uri="https://api.calendly.com/scheduled_events/SESS1",
        calendly_invitee_uri="https://api.calendly.com/scheduled_events/SESS1/invitees/INV1",
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    return client


def test_reschedule_menu_uses_client_facing_calendly_links(db_session):
    client = _seed_client_session(db_session)

    with (
        patch("app.services.bot.reschedule.decrypt_string", return_value="plain-pat"),
        patch(
            "app.services.bot.reschedule.get_invitee_links_with_pat",
            return_value={
                "reschedule_url": "https://calendly.com/reschedulings/ABC123",
                "cancel_url": "https://calendly.com/cancellations/ABC123",
            },
        ),
    ):
        upcoming = get_upcoming_sessions_with_links(db_session, client.id)

    assert len(upcoming) == 1
    assert upcoming[0]["reschedule_url"] == "https://calendly.com/reschedulings/ABC123"
    assert upcoming[0]["cancel_url"] == "https://calendly.com/cancellations/ABC123"
    assert "api.calendly.com" not in upcoming[0]["reschedule_url"]
    assert "api.calendly.com" not in upcoming[0]["cancel_url"]


def test_reschedule_menu_never_shows_raw_api_links_when_invitee_links_missing(db_session):
    client = _seed_client_session(db_session)

    with (
        patch("app.services.bot.reschedule.decrypt_string", return_value="plain-pat"),
        patch("app.services.bot.reschedule.get_invitee_links_with_pat", return_value=None),
    ):
        upcoming = get_upcoming_sessions_with_links(db_session, client.id)

    message = build_reschedule_menu(upcoming)
    assert "api.calendly.com" not in message
    assert "help reschedule" in message.lower()
    assert "help cancel" in message.lower()


def test_within_24h_blocks_links_and_directs_to_admin(db_session):
    client = _seed_client_session(db_session, hours_ahead=2)

    with (
        patch("app.services.bot.reschedule.decrypt_string", return_value="plain-pat"),
        patch(
            "app.services.bot.reschedule.get_invitee_links_with_pat",
            return_value={
                "reschedule_url": "https://calendly.com/reschedulings/ABC123",
                "cancel_url": "https://calendly.com/cancellations/ABC123",
            },
        ) as mock_links,
    ):
        upcoming = get_upcoming_sessions_with_links(db_session, client.id)

    # Within the cutoff: flagged, no links fetched.
    assert upcoming[0]["within_cutoff"] is True
    assert upcoming[0]["reschedule_url"] is None
    assert upcoming[0]["cancel_url"] is None
    mock_links.assert_not_called()

    message = build_reschedule_menu(upcoming, admin_whatsapp="+85291234567")
    assert "within 24 hours" in message.lower()
    assert "+85291234567" in message
    assert "calendly.com" not in message


def test_outside_24h_allows_links(db_session):
    client = _seed_client_session(db_session, hours_ahead=48)

    with (
        patch("app.services.bot.reschedule.decrypt_string", return_value="plain-pat"),
        patch(
            "app.services.bot.reschedule.get_invitee_links_with_pat",
            return_value={
                "reschedule_url": "https://calendly.com/reschedulings/ABC123",
                "cancel_url": "https://calendly.com/cancellations/ABC123",
            },
        ),
    ):
        upcoming = get_upcoming_sessions_with_links(db_session, client.id)

    assert upcoming[0]["within_cutoff"] is False
    message = build_reschedule_menu(upcoming, admin_whatsapp="+85291234567")
    assert "https://calendly.com/reschedulings/ABC123" in message
    assert "within 24 hours" not in message.lower()
