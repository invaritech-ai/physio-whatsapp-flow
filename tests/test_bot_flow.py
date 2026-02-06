"""Integration tests for complete bot conversation flows."""

import pytest
from sqlmodel import select

from app.models import Client, MessageLog
from app.services.bot import states
from app.services.bot.router import process_message


class TestNewClientFlow:
    """Test complete flow for new client booking."""

    def test_complete_new_client_booking_flow(
        self, db_session, sample_specialties, sample_therapist, mock_send_whatsapp
    ):
        """Test full conversation flow from greeting to booking link."""
        # Message 1: Initial greeting
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hi",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_NAME

        # Verify client created
        client = db_session.exec(
            select(Client).where(Client.phone_e164 == "+85212345678")
        ).first()
        assert client is not None
        assert client.conversation_state == states.AWAITING_NAME

        # Message 2: Provide name
        form_data["Body"] = "John Smith"
        form_data["MessageSid"] = "SM002"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_DURATION
        db_session.refresh(client)
        assert client.name == "John Smith"

        # Message 3: Select duration (30 min)
        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM003"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_SPECIALTY

        # Message 4: Select specialty (first one)
        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM004"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_TIME_BAND

        # Message 5: Select time band (morning)
        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM005"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_DAYS

        # Message 6: Select days (Monday, Wednesday, Friday)
        form_data["Body"] = "1,3,5"
        form_data["MessageSid"] = "SM006"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_MATCH_CONFIRM

        # Message 7: Confirm match
        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM007"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.IDLE

        # Verify final state
        db_session.refresh(client)
        assert client.conversation_state == states.IDLE
        assert client.preferred_therapist_id == sample_therapist.id
        assert client.conversation_data is None  # Reset after completion

        # Verify all messages logged (7 inbound + 7 outbound = 14 total)
        message_logs = db_session.exec(select(MessageLog)).all()
        assert len(message_logs) == 14
        inbound_logs = [m for m in message_logs if m.direction == "inbound"]
        outbound_logs = [m for m in message_logs if m.direction == "outbound"]
        assert len(inbound_logs) == 7
        assert len(outbound_logs) == 7

    def test_invalid_input_recovery(
        self, db_session, sample_specialties, sample_therapist, mock_send_whatsapp
    ):
        """Test that invalid input re-prompts correctly."""
        # Start conversation
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hello",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        process_message(form_data, db_session)

        # Provide name
        form_data["Body"] = "Jane"
        form_data["MessageSid"] = "SM002"
        process_message(form_data, db_session)

        # Invalid duration choice
        form_data["Body"] = "99"
        form_data["MessageSid"] = "SM003"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_DURATION

        # Valid duration choice (should work)
        form_data["Body"] = "2"
        form_data["MessageSid"] = "SM004"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_SPECIALTY


class TestReturningClientFlow:
    """Test flows for returning clients."""

    def test_returning_client_with_preferred_therapist(
        self, db_session, sample_therapist, mock_send_whatsapp
    ):
        """Returning client with preferred therapist gets rebook shortcut."""
        # Create existing client with preferred therapist
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        # Message: Greeting
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hi again",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_REBOOK_CHOICE

    def test_returning_client_without_preferred_therapist(
        self, db_session, mock_send_whatsapp
    ):
        """Returning client without preferred therapist skips name collection."""
        # Create existing client without preferred therapist
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        # Message: Greeting
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hello",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_DURATION


class TestRebookFlow:
    """Test rebook shortcut flow."""

    def test_rebook_with_same_therapist(
        self, db_session, sample_specialties, sample_therapist, mock_send_whatsapp
    ):
        """Test rebooking with same therapist."""
        # Create client with preferred therapist
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        # Message 1: Greeting (gets rebook menu)
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hi",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)
        assert result["next_state"] == states.AWAITING_REBOOK_CHOICE

        # Message 2: Choose same therapist
        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM002"
        result = process_message(form_data, db_session)
        assert result["next_state"] == states.AWAITING_DURATION

        # Verify preferred therapist preserved
        db_session.refresh(client)
        assert client.preferred_therapist_id == sample_therapist.id

    def test_rebook_with_different_therapist(
        self, db_session, sample_specialties, sample_therapist, mock_send_whatsapp
    ):
        """Test choosing different therapist."""
        # Create client with preferred therapist
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        # Message 1: Greeting
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hello",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)
        assert result["next_state"] == states.AWAITING_REBOOK_CHOICE

        # Message 2: Choose different therapist
        form_data["Body"] = "2"
        form_data["MessageSid"] = "SM002"
        result = process_message(form_data, db_session)
        assert result["next_state"] == states.AWAITING_DURATION

        # Verify preferred therapist cleared
        db_session.refresh(client)
        assert client.preferred_therapist_id is None


class TestRescheduleFlow:
    """Test reschedule/cancel keyword handling."""

    def test_reschedule_keyword_from_idle(
        self, db_session, mock_send_whatsapp
    ):
        """Test 'reschedule' keyword returns upcoming sessions."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "reschedule",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.IDLE

    def test_cancel_keyword_from_idle(
        self, db_session, mock_send_whatsapp
    ):
        """Test 'cancel' keyword returns upcoming sessions."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "I want to cancel",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.IDLE


class TestStartOverFlow:
    """Test starting over from match confirmation."""

    def test_restart_from_match_confirmation(
        self, db_session, sample_specialties, sample_therapist, mock_send_whatsapp
    ):
        """Test choosing to start over changes preferences."""
        # Create client mid-conversation
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_MATCH_CONFIRM,
        )
        client.conversation_data = '{"duration": 30, "specialty_id": 1, "matched_therapist_id": 1}'
        db_session.add(client)
        db_session.commit()

        # Choose to start over (option 2)
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "2",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_DURATION

        # Verify conversation data reset
        db_session.refresh(client)
        assert client.conversation_data is None


class TestMessageLoggingInFlow:
    """Test that all messages are properly logged during flow."""

    def test_all_messages_logged_with_client_id(
        self, db_session, sample_specialties, sample_therapist, mock_send_whatsapp
    ):
        """Verify all inbound and outbound messages have client_id."""
        # Simple 3-message flow
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hi",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        process_message(form_data, db_session)

        form_data["Body"] = "John"
        form_data["MessageSid"] = "SM002"
        process_message(form_data, db_session)

        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM003"
        process_message(form_data, db_session)

        # Verify all messages have client_id
        message_logs = db_session.exec(select(MessageLog)).all()
        assert len(message_logs) == 6  # 3 inbound + 3 outbound
        assert all(m.client_id is not None for m in message_logs)

        # Verify all messages have same client_id
        client_ids = set(m.client_id for m in message_logs)
        assert len(client_ids) == 1
