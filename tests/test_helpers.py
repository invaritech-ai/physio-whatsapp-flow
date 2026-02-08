"""Unit tests for bot helper utilities."""

import pytest
from sqlmodel import select

from app.models import Client
from app.services.bot.helpers import (
    get_conversation_data,
    get_or_create_client,
    reset_conversation,
    send_and_log,
    set_conversation_data,
    update_conversation_data,
    validate_comma_separated_choices,
    validate_numbered_choice,
)


class TestGetOrCreateClient:
    """Tests for get_or_create_client function."""

    def test_creates_new_client_with_clean_phone(self, db_session):
        """Should create new client with clean E.164 phone."""
        phone = "+85212345678"
        client = get_or_create_client(db_session, phone)

        assert client.id is not None
        assert client.phone_e164 == phone
        assert client.conversation_state == "IDLE"

    def test_creates_new_client_strips_whatsapp_prefix(self, db_session):
        """Should strip 'whatsapp:' prefix when creating client."""
        phone_with_prefix = "whatsapp:+85212345678"
        client = get_or_create_client(db_session, phone_with_prefix)

        assert client.phone_e164 == "+85212345678"

    def test_returns_existing_client(self, db_session):
        """Should return existing client without creating duplicate."""
        phone = "+85212345678"

        # Create first time
        client1 = get_or_create_client(db_session, phone)
        client1_id = client1.id

        # Get second time
        client2 = get_or_create_client(db_session, phone)

        assert client2.id == client1_id
        # Verify only one client exists
        all_clients = db_session.exec(select(Client)).all()
        assert len(all_clients) == 1

    def test_returns_existing_client_with_prefix(self, db_session):
        """Should return existing client even when whatsapp: prefix used."""
        phone = "+85212345678"

        # Create without prefix
        client1 = get_or_create_client(db_session, phone)

        # Get with prefix
        client2 = get_or_create_client(db_session, f"whatsapp:{phone}")

        assert client2.id == client1.id


class TestConversationData:
    """Tests for conversation_data JSON helpers."""

    def test_get_conversation_data_empty(self, sample_client):
        """Should return empty dict when conversation_data is None."""
        sample_client.conversation_data = None
        data = get_conversation_data(sample_client)
        assert data == {}

    def test_get_conversation_data_valid_json(self, sample_client):
        """Should parse valid JSON conversation_data."""
        sample_client.conversation_data = '{"duration": 30, "specialty_id": 2}'
        data = get_conversation_data(sample_client)
        assert data == {"duration": 30, "specialty_id": 2}

    def test_get_conversation_data_invalid_json(self, sample_client):
        """Should return empty dict for invalid JSON."""
        sample_client.conversation_data = "not valid json"
        data = get_conversation_data(sample_client)
        assert data == {}

    def test_set_conversation_data(self, sample_client):
        """Should serialize dict to JSON string."""
        data = {"duration": 45, "time_band": "morning"}
        set_conversation_data(sample_client, data)
        import json
        assert json.loads(sample_client.conversation_data) == data

    def test_update_conversation_data_adds_new_keys(self, sample_client):
        """Should add new keys to conversation_data."""
        sample_client.conversation_data = '{"duration": 30}'
        result = update_conversation_data(sample_client, specialty_id=2, time_band="afternoon")

        assert result == {"duration": 30, "specialty_id": 2, "time_band": "afternoon"}
        # Verify data was saved to client
        saved_data = get_conversation_data(sample_client)
        assert saved_data == result

    def test_update_conversation_data_overwrites_existing(self, sample_client):
        """Should overwrite existing keys in conversation_data."""
        sample_client.conversation_data = '{"duration": 30, "specialty_id": 1}'
        result = update_conversation_data(sample_client, duration=60)

        assert result == {"duration": 60, "specialty_id": 1}

    def test_update_conversation_data_from_empty(self, sample_client):
        """Should work when conversation_data is None."""
        sample_client.conversation_data = None
        result = update_conversation_data(sample_client, duration=30)

        assert result == {"duration": 30}


class TestValidateNumberedChoice:
    """Tests for validate_numbered_choice function."""

    def test_valid_single_digit(self):
        """Should extract valid single digit choices."""
        assert validate_numbered_choice("1", [1, 2, 3]) == 1
        assert validate_numbered_choice("2", [1, 2, 3]) == 2
        assert validate_numbered_choice("3", [1, 2, 3]) == 3

    def test_digit_with_whitespace(self):
        """Should handle whitespace around digit."""
        assert validate_numbered_choice(" 1 ", [1, 2, 3]) == 1
        assert validate_numbered_choice("  2  ", [1, 2, 3]) == 2

    def test_digit_in_sentence(self):
        """Should extract digit from natural language."""
        assert validate_numbered_choice("I choose 1", [1, 2, 3]) == 1
        assert validate_numbered_choice("2 please", [1, 2, 3]) == 2
        assert validate_numbered_choice("I want option 3", [1, 2, 3]) == 3

    def test_digit_with_punctuation(self):
        """Should handle digit with punctuation."""
        assert validate_numbered_choice("1.", [1, 2, 3]) == 1
        assert validate_numbered_choice("2!", [1, 2, 3]) == 2

    def test_invalid_choice_not_in_list(self):
        """Should return None for choice not in valid_choices."""
        assert validate_numbered_choice("4", [1, 2, 3]) is None
        assert validate_numbered_choice("0", [1, 2, 3]) is None

    def test_no_digit_found(self):
        """Should return None when no digit in input."""
        assert validate_numbered_choice("hello", [1, 2, 3]) is None
        assert validate_numbered_choice("", [1, 2, 3]) is None

    def test_case_insensitive(self):
        """Should work case-insensitively."""
        assert validate_numbered_choice("I CHOOSE 1", [1, 2, 3]) == 1


class TestValidateCommaSeparatedChoices:
    """Tests for validate_comma_separated_choices function."""

    def test_comma_separated(self):
        """Should parse comma-separated numbers."""
        assert validate_comma_separated_choices("1,2,3", [1, 2, 3, 4, 5]) == [1, 2, 3]
        assert validate_comma_separated_choices("1, 2, 3", [1, 2, 3, 4, 5]) == [1, 2, 3]

    def test_space_separated(self):
        """Should parse space-separated numbers."""
        assert validate_comma_separated_choices("1 2 3", [1, 2, 3, 4, 5]) == [1, 2, 3]
        assert validate_comma_separated_choices("1  2  3", [1, 2, 3, 4, 5]) == [1, 2, 3]

    def test_mixed_separators(self):
        """Should handle mixed separators."""
        assert validate_comma_separated_choices("1, 2 3", [1, 2, 3, 4, 5]) == [1, 2, 3]
        assert validate_comma_separated_choices("1,2 3,4", [1, 2, 3, 4, 5]) == [1, 2, 3, 4]

    def test_removes_duplicates_preserves_order(self):
        """Should remove duplicates while preserving first occurrence order."""
        assert validate_comma_separated_choices("1,2,1,3", [1, 2, 3]) == [1, 2, 3]
        assert validate_comma_separated_choices("3,1,3,2", [1, 2, 3]) == [3, 1, 2]

    def test_invalid_choice_not_in_list(self):
        """Should return None if any choice invalid."""
        assert validate_comma_separated_choices("1,2,9", [1, 2, 3]) is None
        assert validate_comma_separated_choices("0,1", [1, 2, 3]) is None

    def test_no_numbers_found(self):
        """Should return None when no numbers in input."""
        assert validate_comma_separated_choices("hello", [1, 2, 3]) is None
        assert validate_comma_separated_choices("", [1, 2, 3]) is None

    def test_single_number(self):
        """Should work with single number."""
        assert validate_comma_separated_choices("1", [1, 2, 3]) == [1]

    def test_days_use_case(self):
        """Should work for day selection (1-7)."""
        valid_days = [1, 2, 3, 4, 5, 6, 7]
        assert validate_comma_separated_choices("1,3,5", valid_days) == [1, 3, 5]
        assert validate_comma_separated_choices("1, 2, 3, 4, 5", valid_days) == [1, 2, 3, 4, 5]


class TestSendAndLog:
    """Tests for send_and_log function."""

    def test_sends_message_and_logs(self, db_session, sample_client, mock_send_whatsapp):
        """Should send WhatsApp message and create MessageLog entry."""
        from app.models import MessageLog

        phone = sample_client.phone_e164
        body = "Test message"

        twilio_sid = send_and_log(db_session, phone, body, sample_client.id)

        # Verify Twilio was called with whatsapp: prefix
        mock_send_whatsapp.assert_called_once_with(f"whatsapp:{phone}", body, None)
        assert twilio_sid.startswith("SM")  # Mock returns unique SIDs starting with SM

        # Verify message was logged
        message_log = db_session.exec(select(MessageLog)).first()
        assert message_log is not None
        assert message_log.direction == "outbound"
        assert message_log.phone_e164 == phone
        assert message_log.body == body
        assert message_log.twilio_sid == twilio_sid
        assert message_log.client_id == sample_client.id

    def test_adds_whatsapp_prefix_if_missing(self, db_session, sample_client, mock_send_whatsapp):
        """Should add 'whatsapp:' prefix if not present."""
        phone = "+85212345678"
        send_and_log(db_session, phone, "Test", sample_client.id)

        # Verify Twilio was called with prefix
        mock_send_whatsapp.assert_called_once()
        call_args = mock_send_whatsapp.call_args[0]
        assert call_args[0] == f"whatsapp:{phone}"

    def test_preserves_whatsapp_prefix_if_present(self, db_session, sample_client, mock_send_whatsapp):
        """Should not double-add 'whatsapp:' prefix."""
        phone = "whatsapp:+85212345678"
        send_and_log(db_session, phone, "Test", sample_client.id)

        # Verify Twilio was called with single prefix
        mock_send_whatsapp.assert_called_once()
        call_args = mock_send_whatsapp.call_args[0]
        assert call_args[0] == phone
        assert call_args[0].count("whatsapp:") == 1


class TestResetConversation:
    """Tests for reset_conversation function."""

    def test_resets_to_idle_and_clears_data(self, db_session, sample_client):
        """Should reset conversation_state to IDLE and clear conversation_data."""
        # Set up client with conversation in progress
        sample_client.conversation_state = "AWAITING_DURATION"
        sample_client.conversation_data = '{"duration": 30, "specialty_id": 2}'
        db_session.add(sample_client)
        db_session.commit()

        # Reset
        reset_conversation(sample_client, db_session)

        # Verify reset
        assert sample_client.conversation_state == "IDLE"
        assert sample_client.conversation_data is None

        # Verify persisted to DB
        db_session.refresh(sample_client)
        assert sample_client.conversation_state == "IDLE"
        assert sample_client.conversation_data is None

    def test_reset_when_already_idle(self, db_session, sample_client):
        """Should work even when already IDLE."""
        sample_client.conversation_state = "IDLE"
        sample_client.conversation_data = None

        reset_conversation(sample_client, db_session)

        assert sample_client.conversation_state == "IDLE"
        assert sample_client.conversation_data is None
