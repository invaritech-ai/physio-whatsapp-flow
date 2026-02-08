"""Unit tests for message logging service."""

from datetime import datetime, timezone

import pytest
from sqlmodel import select

from app.models import MessageLog
from app.services.message_logger import log_inbound, log_outbound


class TestLogInbound:
    """Tests for log_inbound function."""

    def test_logs_basic_inbound_message(self, db_session, sample_client):
        """Should create MessageLog entry for inbound message."""
        phone = "+85212345678"
        body = "Hello, I need help"
        twilio_sid = "SM123456"

        message = log_inbound(
            db=db_session,
            phone_e164=phone,
            body=body,
            twilio_sid=twilio_sid,
            client_id=sample_client.id,
        )

        assert message.id is not None
        assert message.direction == "inbound"
        assert message.phone_e164 == phone
        assert message.body == body
        assert message.twilio_sid == twilio_sid
        assert message.client_id == sample_client.id
        assert message.media_url is None
        assert isinstance(message.created_at, datetime)
        # Note: SQLite in-memory doesn't preserve timezone, but PostgreSQL does

    def test_logs_inbound_with_media(self, db_session, sample_client):
        """Should log inbound message with media URL."""
        phone = "+85212345678"
        body = ""
        media_url = "https://api.twilio.com/media/ME123456"

        message = log_inbound(
            db=db_session,
            phone_e164=phone,
            body=body,
            twilio_sid="SM123",
            client_id=sample_client.id,
            media_url=media_url,
        )

        assert message.media_url == media_url

    def test_logs_inbound_without_client_id(self, db_session):
        """Should allow logging without client_id (new user)."""
        message = log_inbound(
            db=db_session,
            phone_e164="+85212345678",
            body="Hello",
            twilio_sid="SM123",
            client_id=None,
        )

        assert message.client_id is None
        assert message.id is not None

    def test_logs_inbound_without_twilio_sid(self, db_session, sample_client):
        """Should allow logging without Twilio SID (test scenarios)."""
        message = log_inbound(
            db=db_session,
            phone_e164="+85212345678",
            body="Test message",
            twilio_sid=None,
            client_id=sample_client.id,
        )

        assert message.twilio_sid is None
        assert message.id is not None

    def test_message_persisted_to_database(self, db_session, sample_client):
        """Should persist message to database."""
        log_inbound(
            db=db_session,
            phone_e164="+85212345678",
            body="Test",
            twilio_sid="SM123",
            client_id=sample_client.id,
        )

        # Query database to verify
        messages = db_session.exec(select(MessageLog).order_by(MessageLog.id)).all()
        assert len(messages) == 1
        assert messages[0].direction == "inbound"


class TestLogOutbound:
    """Tests for log_outbound function."""

    def test_logs_basic_outbound_message(self, db_session, sample_client):
        """Should create MessageLog entry for outbound message."""
        phone = "+85212345678"
        body = "Thanks for contacting us!"
        twilio_sid = "SM789012"

        message = log_outbound(
            db=db_session,
            phone_e164=phone,
            body=body,
            twilio_sid=twilio_sid,
            client_id=sample_client.id,
        )

        assert message.id is not None
        assert message.direction == "outbound"
        assert message.phone_e164 == phone
        assert message.body == body
        assert message.twilio_sid == twilio_sid
        assert message.client_id == sample_client.id
        assert isinstance(message.created_at, datetime)
        # Note: SQLite in-memory doesn't preserve timezone, but PostgreSQL does

    def test_logs_outbound_without_client_id(self, db_session):
        """Should allow logging without client_id."""
        message = log_outbound(
            db=db_session,
            phone_e164="+85212345678",
            body="Welcome!",
            twilio_sid="SM123",
            client_id=None,
        )

        assert message.client_id is None
        assert message.id is not None

    def test_message_persisted_to_database(self, db_session, sample_client):
        """Should persist message to database."""
        log_outbound(
            db=db_session,
            phone_e164="+85212345678",
            body="Test reply",
            twilio_sid="SM456",
            client_id=sample_client.id,
        )

        # Query database to verify
        messages = db_session.exec(select(MessageLog).order_by(MessageLog.id)).all()
        assert len(messages) == 1
        assert messages[0].direction == "outbound"


class TestMessageLoggingIntegration:
    """Integration tests for message logging."""

    def test_logs_full_conversation(self, db_session, sample_client):
        """Should log both inbound and outbound messages in conversation."""
        # User sends message
        log_inbound(
            db=db_session,
            phone_e164=sample_client.phone_e164,
            body="Hi",
            twilio_sid="SM111",
            client_id=sample_client.id,
        )

        # Bot replies
        log_outbound(
            db=db_session,
            phone_e164=sample_client.phone_e164,
            body="Hello! What's your name?",
            twilio_sid="SM222",
            client_id=sample_client.id,
        )

        # User responds
        log_inbound(
            db=db_session,
            phone_e164=sample_client.phone_e164,
            body="John",
            twilio_sid="SM333",
            client_id=sample_client.id,
        )

        # Bot replies
        log_outbound(
            db=db_session,
            phone_e164=sample_client.phone_e164,
            body="Nice to meet you, John!",
            twilio_sid="SM444",
            client_id=sample_client.id,
        )

        # Verify all 4 messages logged (ordered by id for deterministic assertions)
        messages = db_session.exec(
            select(MessageLog).order_by(MessageLog.id)
        ).all()
        assert len(messages) == 4

        # Verify order (should be chronological by insertion)
        assert messages[0].direction == "inbound"
        assert messages[0].body == "Hi"
        assert messages[1].direction == "outbound"
        assert messages[1].body == "Hello! What's your name?"
        assert messages[2].direction == "inbound"
        assert messages[2].body == "John"
        assert messages[3].direction == "outbound"
        assert messages[3].body == "Nice to meet you, John!"

        # Verify all linked to same client
        assert all(m.client_id == sample_client.id for m in messages)

    def test_query_messages_by_client(self, db_session, sample_client):
        """Should be able to query messages for specific client."""
        # Create another client
        from app.models import Client

        other_client = Client(phone_e164="+85298765432", conversation_state="IDLE")
        db_session.add(other_client)
        db_session.commit()
        db_session.refresh(other_client)

        # Log messages for both clients
        log_inbound(db_session, sample_client.phone_e164, "Hello", "SM1", sample_client.id)
        log_inbound(db_session, other_client.phone_e164, "Hi there", "SM2", other_client.id)

        # Query messages for sample_client only
        stmt = select(MessageLog).where(MessageLog.client_id == sample_client.id)
        client_messages = db_session.exec(stmt).all()

        assert len(client_messages) == 1
        assert client_messages[0].body == "Hello"

    def test_query_messages_by_direction(self, db_session, sample_client):
        """Should be able to query by message direction."""
        log_inbound(db_session, sample_client.phone_e164, "Question?", "SM1", sample_client.id)
        log_outbound(db_session, sample_client.phone_e164, "Answer!", "SM2", sample_client.id)
        log_inbound(db_session, sample_client.phone_e164, "Thanks", "SM3", sample_client.id)

        # Query inbound only
        stmt = select(MessageLog).where(MessageLog.direction == "inbound")
        inbound = db_session.exec(stmt).all()
        assert len(inbound) == 2

        # Query outbound only
        stmt = select(MessageLog).where(MessageLog.direction == "outbound")
        outbound = db_session.exec(stmt).all()
        assert len(outbound) == 1
