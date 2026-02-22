"""Integration tests for complete bot conversation flows."""

import json

import pytest
from sqlmodel import select

from app.models import Client, MessageLog, Therapist, User
from app.services.bot import states
from app.services.bot.router import process_message


class TestNewClientFlow:
    """Test complete flow for new client booking."""

    def test_complete_new_client_booking_flow(
        self, db_session, sample_specialties, sample_therapist, mock_send_whatsapp
    ):
        """Test full conversation flow from greeting to booking link."""
        # Message 1: Initial greeting → main menu (asks for name)
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hi",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.IDLE

        # Verify client created
        client = db_session.exec(
            select(Client).where(Client.phone_e164 == "+85212345678")
        ).first()
        assert client is not None
        assert client.conversation_state == states.IDLE

        # Message 2: Provide name → proceeds to booking-path selection
        form_data["Body"] = "John Smith"
        form_data["MessageSid"] = "SM002"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_BOOKING_PATH
        db_session.refresh(client)
        assert client.name == "John Smith"

        # Message 3: Choose smart match path
        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM003"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_DURATION

        # Message 4: Select duration (30 min)
        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM004"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_SPECIALTY

        # Message 5: Select specialty (first one)
        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM005"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_TIME_BAND

        # Message 6: Select time band
        form_data["Body"] = "1"
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

        # Choose smart-match path first
        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM003"
        process_message(form_data, db_session)

        # Invalid duration choice
        form_data["Body"] = "99"
        form_data["MessageSid"] = "SM004"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_DURATION

        # Valid duration choice (should work)
        form_data["Body"] = "2"
        form_data["MessageSid"] = "SM005"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_SPECIALTY


class TestReturningClientFlow:
    """Test flows for returning clients."""

    def test_returning_client_with_preferred_therapist(
        self, db_session, sample_therapist, mock_send_whatsapp
    ):
        """Returning client with preferred therapist sees main menu with rebook option."""
        # Create existing client with preferred therapist
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        # Message 1: Greeting → main menu with rebook options
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hi",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.IDLE

        # Message 2: Choose option 1 (rebook with same therapist)
        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM002"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_DURATION

    def test_returning_client_without_preferred_therapist(
        self, db_session, mock_send_whatsapp
    ):
        """Returning client without preferred therapist sees main menu."""
        # Create existing client without preferred therapist
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        # Message 1: Greeting → main menu
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hello",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.IDLE

        # Message 2: Choose option 1 (book session)
        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM002"
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_DURATION


class TestRebookFlow:
    """Test rebook shortcut flow."""

    def test_rebook_with_same_therapist(
        self, db_session, sample_specialties, sample_therapist, mock_send_whatsapp
    ):
        """Test rebooking with same therapist via main menu."""
        # Create client with preferred therapist
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        # Message 1: Greeting → main menu
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hi",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)
        assert result["next_state"] == states.IDLE

        # Message 2: Choose option 1 (rebook same therapist)
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
        """Test choosing different therapist via main menu."""
        # Create client with preferred therapist
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        # Message 1: Greeting → main menu
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hello",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)
        assert result["next_state"] == states.IDLE

        # Message 2: Choose option 2 (different therapist)
        form_data["Body"] = "2"
        form_data["MessageSid"] = "SM002"
        result = process_message(form_data, db_session)
        assert result["next_state"] == states.AWAITING_DURATION

        # Verify preferred therapist kept, but excluded via conversation_data
        db_session.refresh(client)
        assert client.preferred_therapist_id == sample_therapist.id
        conv_data = json.loads(client.conversation_data)
        assert conv_data["exclude_therapist_id"] == sample_therapist.id


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


class TestGlobalKeywordMidFlow:
    """Test global keywords interrupt mid-flow and reset to menu."""

    def test_menu_keyword_resets_from_mid_flow(
        self, db_session, mock_send_whatsapp
    ):
        """Typing 'menu' mid-booking resets to main menu."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_SPECIALTY,
        )
        client.conversation_data = '{"duration": 30}'
        db_session.add(client)
        db_session.commit()

        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "menu",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.IDLE

        # Verify conversation data was reset
        db_session.refresh(client)
        assert client.conversation_data is None

    def test_book_keyword_from_mid_flow(
        self, db_session, mock_send_whatsapp
    ):
        """Typing 'book' mid-flow jumps straight to booking."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_SPECIALTY,
        )
        client.conversation_data = '{"duration": 30}'
        db_session.add(client)
        db_session.commit()

        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "book",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        assert result["status"] == "success"
        assert result["next_state"] == states.AWAITING_BOOKING_PATH

    def test_reschedule_keyword_from_mid_flow(
        self, db_session, mock_send_whatsapp
    ):
        """Typing 'reschedule' mid-flow shows reschedule menu."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DURATION,
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
        assert result["next_state"] == states.AWAITING_BOOKING_PATH

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

class TestMediaAndEmptyMessages:
    """Test handling of media-only and empty messages."""

    def test_media_only_message_is_logged(
        self, db_session, mock_send_whatsapp
    ):
        """Media-only messages (empty body) should be logged and get a response."""
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "",  # Empty body
            "MessageSid": "SM001",
            "NumMedia": "1",
            "MediaUrl0": "https://api.twilio.com/media/ME123456",
        }
        result = process_message(form_data, db_session)

        # Should succeed with helpful message
        assert result["status"] == "success"
        assert "note" in result
        assert result["note"] == "Empty body or media-only message"

        # Verify inbound message was logged with media_url
        inbound_logs = db_session.exec(
            select(MessageLog).where(MessageLog.direction == "inbound")
        ).all()
        assert len(inbound_logs) == 1
        assert inbound_logs[0].body == ""
        assert inbound_logs[0].media_url == "https://api.twilio.com/media/ME123456"

        # Verify outbound response was sent and logged
        outbound_logs = db_session.exec(
            select(MessageLog).where(MessageLog.direction == "outbound")
        ).all()
        assert len(outbound_logs) == 1
        assert "text message" in outbound_logs[0].body.lower()

    def test_blank_message_is_logged(
        self, db_session, mock_send_whatsapp
    ):
        """Blank messages (whitespace only) should be logged and get a response."""
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "   ",  # Whitespace only
            "MessageSid": "SM002",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        # Should succeed with helpful message
        assert result["status"] == "success"
        assert "note" in result

        # Verify message was logged
        message_logs = db_session.exec(select(MessageLog)).all()
        assert len(message_logs) == 2  # 1 inbound + 1 outbound

    def test_missing_sender_returns_error(
        self, db_session, mock_send_whatsapp
    ):
        """Missing sender should return error (no logging possible)."""
        form_data = {
            "From": "",  # Empty sender
            "Body": "Hello",
            "MessageSid": "SM003",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)

        # Should fail
        assert result["status"] == "error"
        assert "From" in result["message"]

        # Verify no messages logged (can't create client without phone)
        message_logs = db_session.exec(select(MessageLog)).all()
        assert len(message_logs) == 0

    def test_rebook_uses_preferred_therapist(
        self, db_session, sample_specialties, mock_send_whatsapp
    ):
        """Rebooking with same therapist should actually use preferred therapist."""
        # Create two therapists
        user1 = User(
            neon_auth_sub="auth-1",
            email="therapist1@test.com",
            display_name="Dr. One",
            role="therapist",
            is_active=True,
        )
        user2 = User(
            neon_auth_sub="auth-2",
            email="therapist2@test.com",
            display_name="Dr. Two",
            role="therapist",
            is_active=True,
        )
        db_session.add(user1)
        db_session.add(user2)
        db_session.commit()

        therapist1 = Therapist(user_id=user1.id, display_name="Dr. One", is_active=True)
        therapist2 = Therapist(user_id=user2.id, display_name="Dr. Two", is_active=True)
        db_session.add(therapist1)
        db_session.add(therapist2)
        db_session.commit()
        db_session.refresh(therapist1)
        db_session.refresh(therapist2)

        # Create client with preferred therapist 2
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=therapist2.id,
        )
        db_session.add(client)
        db_session.commit()

        # Start rebook flow: greeting → main menu
        form_data = {
            "From": "whatsapp:+85212345678",
            "Body": "Hi",
            "MessageSid": "SM001",
            "NumMedia": "0",
        }
        result = process_message(form_data, db_session)
        assert result["next_state"] == states.IDLE

        # Choose option 1 (rebook same therapist)
        form_data["Body"] = "1"
        form_data["MessageSid"] = "SM002"
        result = process_message(form_data, db_session)
        assert result["next_state"] == states.AWAITING_DURATION

        # Verify preferred therapist has been pinned for direct duration->link path.
        db_session.refresh(client)
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("selected_therapist_id") == therapist2.id
        assert conv_data.get("book_by_name") is True
