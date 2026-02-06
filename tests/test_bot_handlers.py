"""Unit tests for bot state handlers."""

import json

import pytest

from app.models import Client, Therapist, TherapistSpecialty, User
from app.services.bot import states
from app.services.bot.handlers import (
    handle_awaiting_days,
    handle_awaiting_duration,
    handle_awaiting_match_confirm,
    handle_awaiting_name,
    handle_awaiting_rebook_choice,
    handle_awaiting_specialty,
    handle_awaiting_time_band,
    handle_idle,
    handle_reschedule_request,
)
from app.services.bot.helpers import update_conversation_data


class TestHandleIdle:
    """Tests for handle_idle function."""

    def test_new_client_asks_for_name(self, db_session):
        """New client without name should be asked for name."""
        client = Client(phone_e164="+85212345678", conversation_state=states.IDLE)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "hi", db_session)

        assert next_state == states.AWAITING_NAME
        assert "name" in response.lower()

    def test_returning_client_without_preferred_therapist(self, db_session):
        """Returning client without preferred therapist goes to duration."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "hello", db_session)

        assert next_state == states.AWAITING_DURATION
        assert "John" in response

    def test_returning_client_with_preferred_therapist(
        self, db_session, sample_therapist
    ):
        """Returning client with preferred therapist gets rebook menu."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "hi", db_session)

        assert next_state == states.AWAITING_REBOOK_CHOICE
        assert "John" in response
        assert sample_therapist.display_name in response

    def test_reschedule_keyword_triggers_reschedule_flow(self, db_session):
        """Reschedule keyword should trigger reschedule handler."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "reschedule", db_session)

        assert next_state == states.IDLE
        # Should show upcoming appointments (even if empty)
        assert "appointment" in response.lower()


class TestHandleAwaitingName:
    """Tests for handle_awaiting_name function."""

    def test_valid_name_saves_and_proceeds(self, db_session):
        """Valid name should be saved and proceed to duration."""
        client = Client(
            phone_e164="+85212345678", conversation_state=states.AWAITING_NAME
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_name(client, "john smith", db_session)

        assert next_state == states.AWAITING_DURATION
        assert client.name == "John Smith"  # Should be title-cased
        assert "John Smith" in response

    def test_name_too_short_rejects(self, db_session):
        """Name shorter than 2 characters should be rejected."""
        client = Client(
            phone_e164="+85212345678", conversation_state=states.AWAITING_NAME
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_name(client, "j", db_session)

        assert next_state == states.AWAITING_NAME
        assert "valid name" in response.lower()
        assert client.name is None

    def test_numeric_name_rejects(self, db_session):
        """Numeric input should be rejected."""
        client = Client(
            phone_e164="+85212345678", conversation_state=states.AWAITING_NAME
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_name(client, "123", db_session)

        assert next_state == states.AWAITING_NAME
        assert "name" in response.lower()
        assert client.name is None


class TestHandleAwaitingDuration:
    """Tests for handle_awaiting_duration function."""

    def test_valid_duration_choice_1_saves_30min(
        self, db_session, sample_specialties
    ):
        """Choice 1 should save 30 minutes."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DURATION,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_duration(client, "1", db_session)

        assert next_state == states.AWAITING_SPECIALTY
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("duration") == 30

    def test_valid_duration_choice_2_saves_45min(
        self, db_session, sample_specialties
    ):
        """Choice 2 should save 45 minutes."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DURATION,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_duration(client, "2", db_session)

        assert next_state == states.AWAITING_SPECIALTY
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("duration") == 45

    def test_valid_duration_choice_3_saves_60min(
        self, db_session, sample_specialties
    ):
        """Choice 3 should save 60 minutes."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DURATION,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_duration(client, "3", db_session)

        assert next_state == states.AWAITING_SPECIALTY
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("duration") == 60

    def test_invalid_duration_choice_rejects(self, db_session):
        """Invalid choice should be rejected."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DURATION,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_duration(client, "4", db_session)

        assert next_state == states.AWAITING_DURATION
        assert "1" in response and "2" in response and "3" in response


class TestHandleAwaitingSpecialty:
    """Tests for handle_awaiting_specialty function."""

    def test_valid_specialty_choice_saves(self, db_session, sample_specialties):
        """Valid specialty choice should be saved."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_SPECIALTY,
        )
        update_conversation_data(client, duration=30)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_specialty(client, "1", db_session)

        assert next_state == states.AWAITING_TIME_BAND
        conv_data = json.loads(client.conversation_data or "{}")
        # Choice 1 should be the first specialty alphabetically
        sorted_specialties = sorted(sample_specialties, key=lambda s: s.name)
        assert conv_data.get("specialty_id") == sorted_specialties[0].id

    def test_invalid_specialty_choice_rejects(self, db_session, sample_specialties):
        """Invalid choice should be rejected."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_SPECIALTY,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_specialty(client, "99", db_session)

        assert next_state == states.AWAITING_SPECIALTY
        assert "please reply" in response.lower()


class TestHandleAwaitingTimeBand:
    """Tests for handle_awaiting_time_band function."""

    def test_choice_1_saves_morning(self, db_session):
        """Choice 1 should save morning time band."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_TIME_BAND,
        )
        update_conversation_data(client, duration=30, specialty_id=1)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_time_band(client, "1", db_session)

        assert next_state == states.AWAITING_DAYS
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("time_band") == states.TIME_BAND_MORNING

    def test_choice_2_saves_afternoon(self, db_session):
        """Choice 2 should save afternoon time band."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_TIME_BAND,
        )
        update_conversation_data(client, duration=30, specialty_id=1)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_time_band(client, "2", db_session)

        assert next_state == states.AWAITING_DAYS
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("time_band") == states.TIME_BAND_AFTERNOON

    def test_choice_3_saves_evening(self, db_session):
        """Choice 3 should save evening time band."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_TIME_BAND,
        )
        update_conversation_data(client, duration=30, specialty_id=1)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_time_band(client, "3", db_session)

        assert next_state == states.AWAITING_DAYS
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("time_band") == states.TIME_BAND_EVENING


class TestHandleAwaitingDays:
    """Tests for handle_awaiting_days function."""

    def test_valid_single_day_saves(self, db_session, sample_therapist):
        """Single valid day should be saved."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DAYS,
        )
        update_conversation_data(
            client, duration=30, specialty_id=1, time_band=states.TIME_BAND_MORNING
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_days(client, "1", db_session)

        assert next_state == states.AWAITING_MATCH_CONFIRM
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("days") == [1]
        assert "matched_therapist_id" in conv_data

    def test_valid_multiple_days_saves(self, db_session, sample_therapist):
        """Multiple valid days should be saved."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DAYS,
        )
        update_conversation_data(
            client, duration=30, specialty_id=1, time_band=states.TIME_BAND_MORNING
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_days(client, "1,3,5", db_session)

        assert next_state == states.AWAITING_MATCH_CONFIRM
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("days") == [1, 3, 5]

    def test_invalid_days_rejects(self, db_session):
        """Invalid day numbers should be rejected."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DAYS,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_days(client, "8,9", db_session)

        assert next_state == states.AWAITING_DAYS
        assert "valid day numbers" in response.lower()


class TestHandleAwaitingMatchConfirm:
    """Tests for handle_awaiting_match_confirm function."""

    def test_choice_1_confirms_and_provides_link(self, db_session, sample_therapist):
        """Choice 1 should confirm match and provide Calendly link."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_MATCH_CONFIRM,
        )
        update_conversation_data(
            client,
            duration=30,
            specialty_id=1,
            matched_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_match_confirm(client, "1", db_session)

        assert next_state == states.IDLE
        assert "calendly.com" in response.lower()
        assert client.preferred_therapist_id == sample_therapist.id
        assert client.conversation_data is None  # Reset

    def test_choice_2_starts_over(self, db_session, sample_therapist):
        """Choice 2 should reset and start over."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_MATCH_CONFIRM,
        )
        update_conversation_data(
            client,
            duration=30,
            specialty_id=1,
            matched_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_match_confirm(client, "2", db_session)

        assert next_state == states.AWAITING_DURATION
        assert client.conversation_data is None  # Reset


class TestHandleAwaitingRebookChoice:
    """Tests for handle_awaiting_rebook_choice function."""

    def test_choice_1_rebooks_with_same_therapist(self, db_session, sample_therapist):
        """Choice 1 should rebook with same therapist."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_REBOOK_CHOICE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_rebook_choice(client, "1", db_session)

        assert next_state == states.AWAITING_DURATION
        assert client.preferred_therapist_id == sample_therapist.id  # Preserved
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("rebooking") is True

    def test_choice_2_clears_preferred_therapist(self, db_session, sample_therapist):
        """Choice 2 should clear preferred therapist."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_REBOOK_CHOICE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_rebook_choice(client, "2", db_session)

        assert next_state == states.AWAITING_DURATION
        assert client.preferred_therapist_id is None  # Cleared


class TestHandleRescheduleRequest:
    """Tests for handle_reschedule_request function."""

    def test_returns_upcoming_sessions(self, db_session):
        """Should return list of upcoming sessions (or empty message)."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_reschedule_request(client, "reschedule", db_session)

        assert next_state == states.IDLE
        assert "appointment" in response.lower()


class TestSpecialtyOrderingConsistency:
    """Test that specialty ordering is consistent between menu and validation."""

    def test_specialties_ordered_alphabetically(self, db_session):
        """Specialties should be ordered by name consistently."""
        # Create specialties in non-alphabetical order
        specialties = [
            TherapistSpecialty(name="Orthopedic", is_active=True),
            TherapistSpecialty(name="Sports Rehab", is_active=True),
            TherapistSpecialty(name="Neurological", is_active=True),
        ]
        for spec in specialties:
            db_session.add(spec)
        db_session.commit()

        # Start flow
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DURATION,
        )
        db_session.add(client)
        db_session.commit()

        # Get menu
        next_state, menu_text = handle_awaiting_duration(client, "1", db_session)
        assert next_state == states.AWAITING_SPECIALTY

        # Menu should show alphabetically: 1=Neurological, 2=Orthopedic, 3=Sports Rehab
        assert "Neurological" in menu_text
        assert "Orthopedic" in menu_text
        assert "Sports Rehab" in menu_text

        # Choose option 1 (should be Neurological, first alphabetically)
        next_state, response = handle_awaiting_specialty(client, "1", db_session)
        assert next_state == states.AWAITING_TIME_BAND

        # Verify correct specialty was saved
        conv_data = json.loads(client.conversation_data or "{}")
        saved_specialty_id = conv_data.get("specialty_id")

        # Should be Neurological (first alphabetically)
        saved_specialty = db_session.get(TherapistSpecialty, saved_specialty_id)
        assert saved_specialty.name == "Neurological"
