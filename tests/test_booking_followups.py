"""Unit tests for booking-link follow-up Celery task."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import select

from app.models import Client, MessageLog
from app.models import Session as TherapySession
from app.models import Therapist, User
from app.tasks.booking_followups import send_booking_link_followup


def _seed_therapist(db_session):
    user = User(
        neon_auth_sub="followup-therapist-sub",
        email="followup-therapist@test.com",
        display_name="Dr. Followup",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name="Dr. Followup",
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return therapist


def test_followup_stage1_sends_when_not_booked(db_session):
    client = Client(phone_e164="+85299990001", name="Client One", conversation_state="IDLE")
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)
    client_id = client.id
    therapist = _seed_therapist(db_session)
    therapist_id = therapist.id

    def fake_get_session():
        yield db_session

    with (
        patch("app.db.session.get_session", fake_get_session),
        patch("app.services.bot.helpers.send_whatsapp_message", return_value="SM-FOLLOWUP-1"),
    ):
        result = send_booking_link_followup(
            client_id=client_id,
            therapist_id=therapist_id,
            duration_minutes=45,
            therapist_name=therapist.display_name,
            scheduling_url="https://calendly.com/dr-followup/45min",
            link_sent_at_iso=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            stage=1,
        )

    assert result["status"] == "sent"
    outbound = db_session.exec(
        select(MessageLog).where(
            MessageLog.client_id == client_id,
            MessageLog.direction == "outbound",
        )
    ).all()
    assert len(outbound) == 1
    assert "Gentle reminder:" in outbound[0].body


def test_followup_skips_when_booking_exists(db_session):
    client = Client(phone_e164="+85299990002", name="Client Two", conversation_state="IDLE")
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)
    client_id = client.id
    therapist = _seed_therapist(db_session)
    therapist_id = therapist.id

    now = datetime.now(timezone.utc)
    session_row = TherapySession(
        client_id=client_id,
        therapist_id=therapist_id,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, minutes=45),
        duration_minutes=45,
        status="scheduled",
        source="calendly",
    )
    db_session.add(session_row)
    db_session.commit()

    def fake_get_session():
        yield db_session

    with patch("app.db.session.get_session", fake_get_session):
        result = send_booking_link_followup(
            client_id=client_id,
            therapist_id=therapist_id,
            duration_minutes=45,
            therapist_name=therapist.display_name,
            scheduling_url="https://calendly.com/dr-followup/45min",
            link_sent_at_iso=(now - timedelta(hours=2)).isoformat(),
            stage=1,
        )

    assert result["status"] == "skipped"
    assert result["reason"] == "already_booked"
    outbound = db_session.exec(
        select(MessageLog).where(
            MessageLog.client_id == client_id,
            MessageLog.direction == "outbound",
        )
    ).all()
    assert len(outbound) == 0
