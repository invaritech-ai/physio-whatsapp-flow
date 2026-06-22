"""Unit tests for bot state handlers."""

import json
from datetime import datetime, timedelta, timezone


from app.models import (
    Client,
    Session as TherapySession,
    Therapist,
    TherapistEventType,
    TherapistSpecialty,
    User,
)
from app.services.bot import states
from app.services.bot.handlers import (
    check_global_keywords,
    handle_awaiting_by_name_duration_options,
    handle_awaiting_days,
    handle_awaiting_duration,
    handle_awaiting_match_preference,
    handle_awaiting_match_confirm,
    handle_awaiting_name,
    handle_awaiting_preferred_name,
    handle_awaiting_time_band,
    handle_idle,
    handle_reschedule_request,
)
from app.services.bot.helpers import update_conversation_data


class TestHandleIdle:
    """Tests for handle_idle — processes main menu numbered choices."""

    def test_new_client_requires_explicit_name_step(self, db_session):
        """Unnamed client should be routed to explicit name prompt first."""
        client = Client(phone_e164="+85212345678", conversation_state=states.IDLE)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "john smith", db_session)

        assert next_state == states.AWAITING_NAME
        assert client.name is None
        assert "official name" in response.lower()

    def test_new_client_invalid_name_stays_for_name(self, db_session):
        """Unnamed client message keeps them in explicit name collection."""
        client = Client(phone_e164="+85212345678", conversation_state=states.IDLE)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "j", db_session)

        assert next_state == states.AWAITING_NAME
        assert "name" in response.lower()

    def test_manage_option_hidden_without_upcoming_sessions(self, db_session):
        """Returning client with no upcoming sessions should not see manage option in menu."""
        client = Client(
            phone_e164="+85212345670",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "9", db_session)

        assert next_state == states.IDLE
        assert "reschedule or cancel" not in response.lower()

    def test_returning_client_choice_1_books_session(self, db_session):
        """Returning client (no preferred therapist) choice 1 starts booking."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "1", db_session)

        assert next_state == states.AWAITING_DURATION
        assert "John" in response

    def test_returning_client_choice_2_opens_by_name_flow(self, db_session, sample_therapist):
        """Returning client (no preferred therapist) choice 2 opens therapist-pick flow."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "2", db_session)

        assert next_state == states.AWAITING_THERAPIST_PICK
        assert sample_therapist.display_name in response

    def test_returning_client_invalid_choice_reshows_menu(self, db_session):
        """Returning client with invalid choice re-shows main menu."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "9", db_session)

        assert next_state == states.IDLE
        assert "book" in response.lower()

    def test_preferred_therapist_choice_1_rebooks(
        self, db_session, sample_therapist
    ):
        """Client with preferred therapist choice 1 rebooks with same therapist."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "1", db_session)

        # Rebooking a preferred therapist now shows that therapist's own durations
        # up front (no generic 45/30/60 prompt that could offer an unavailable one).
        assert next_state == states.AWAITING_BY_NAME_DURATION_OPTIONS
        assert client.preferred_therapist_id == sample_therapist.id
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("rebooking") is True
        assert conv_data.get("by_name_duration_therapist_id") == sample_therapist.id

    def test_preferred_therapist_choice_2_clears_and_books(
        self, db_session, sample_therapist
    ):
        """Client with preferred therapist choice 2 clears preference and books."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "2", db_session)

        assert next_state == states.AWAITING_DURATION
        # preferred_therapist_id kept; excluded via conversation_data
        assert client.preferred_therapist_id == sample_therapist.id
        conv_data = json.loads(client.conversation_data)
        assert conv_data["exclude_therapist_id"] == sample_therapist.id

    def test_preferred_therapist_choice_3_opens_by_name(
        self, db_session, sample_therapist
    ):
        """Client with preferred therapist choice 3 opens by-name flow."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "3", db_session)

        assert next_state == states.AWAITING_THERAPIST_PICK
        assert sample_therapist.display_name in response

    def test_preferred_therapist_invalid_choice_reshows_menu(
        self, db_session, sample_therapist
    ):
        """Client with preferred therapist and invalid choice re-shows menu."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_idle(client, "9", db_session)

        assert next_state == states.IDLE
        assert sample_therapist.display_name in response

    def test_preferred_therapist_choice_4_reschedules(
        self, db_session, sample_therapist
    ):
        """Client with preferred therapist choice 4 shows reschedule."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()
        db_session.refresh(client)

        upcoming = TherapySession(
            client_id=client.id,
            therapist_id=sample_therapist.id,
            start_time=datetime.now(timezone.utc) + timedelta(days=2),
            end_time=datetime.now(timezone.utc) + timedelta(days=2, minutes=45),
            duration_minutes=45,
            source="manual",
            status="scheduled",
        )
        db_session.add(upcoming)
        db_session.commit()

        next_state, response = handle_idle(client, "4", db_session)

        assert next_state == states.IDLE
        assert "appointment" in response.lower()


class TestHandleAwaitingName:
    """Tests for handle_awaiting_name function."""

    def test_valid_name_saves_and_proceeds(self, db_session):
        """Valid name should be saved and proceed to booking path."""
        client = Client(
            phone_e164="+85212345678", conversation_state=states.AWAITING_NAME
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_name(client, "john smith", db_session)

        assert next_state == states.AWAITING_PREFERRED_NAME
        assert client.name == "John Smith"  # Should be title-cased
        assert "John Smith" in response

    def test_name_with_pleasantries_extracts_core_name(self, db_session):
        """Natural-language intro should extract a clean name."""
        client = Client(
            phone_e164="+85212345678", conversation_state=states.AWAITING_NAME
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_name(
            client, "I am Avi. Nice to meet you", db_session
        )

        assert next_state == states.AWAITING_PREFERRED_NAME
        assert client.name == "Avi"
        assert "Avi" in response

    def test_name_too_short_rejects(self, db_session):
        """Name shorter than 2 characters should be rejected."""
        client = Client(
            phone_e164="+85212345678", conversation_state=states.AWAITING_NAME
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_name(client, "j", db_session)

        assert next_state == states.AWAITING_NAME
        assert "valid full name" in response.lower()
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


class TestHandleAwaitingPreferredName:
    """Tests for handle_awaiting_preferred_name function."""

    def test_preferred_name_saved_and_proceeds(self, db_session, sample_specialties):
        client = Client(
            phone_e164="+85212345678",
            name="John Michael Smith",
            conversation_state=states.AWAITING_PREFERRED_NAME,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_preferred_name(client, "John", db_session)

        assert next_state == states.AWAITING_BOOKING_PATH
        assert client.preferred_name == "John"
        assert "John" in response  # greeting addresses preferred name

    def test_skip_defaults_to_first_name(self, db_session, sample_specialties):
        client = Client(
            phone_e164="+85212345678",
            name="John Michael Smith",
            conversation_state=states.AWAITING_PREFERRED_NAME,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_preferred_name(client, "skip", db_session)

        assert next_state == states.AWAITING_BOOKING_PATH
        assert client.preferred_name == "John"


class TestHandleAwaitingDuration:
    """Tests for handle_awaiting_duration function."""

    def test_valid_duration_choice_1_saves_45min(
        self, db_session, sample_specialties
    ):
        """Choice 1 should save 45 minutes."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DURATION,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_duration(client, "1", db_session)

        assert next_state == states.AWAITING_MATCH_PREFERENCE
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("duration") == 45

    def test_valid_duration_choice_2_saves_30min(
        self, db_session, sample_specialties
    ):
        """Choice 2 should save 30 minutes."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DURATION,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_duration(client, "2", db_session)

        assert next_state == states.AWAITING_MATCH_PREFERENCE
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("duration") == 30

    def test_multiple_duration_numbers_rejects(
        self, db_session, sample_specialties
    ):
        """Multiple-number input should be rejected for duration selection."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DURATION,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_duration(client, "1,3", db_session)

        assert next_state == states.AWAITING_DURATION
        assert "1" in response and "2" in response

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
        assert "1" in response and "2" in response

    def test_by_name_unavailable_duration_shows_available_options(self, db_session):
        """By-name flow should switch to duration-options state when selected duration is unavailable."""
        user = User(
            neon_auth_sub="auth-by-name-duration",
            email="by-name-duration@test.com",
            display_name="Dr. Duration",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        therapist = Therapist(user_id=user.id, display_name="Dr. Duration", is_active=True)
        db_session.add(therapist)
        db_session.commit()
        db_session.refresh(therapist)

        event_type = TherapistEventType(
            therapist_id=therapist.id,
            calendly_event_type_uri="https://api.calendly.com/event_types/duration-30",
            duration_minutes=30,
            scheduling_url="https://calendly.com/dr-duration/30min",
            is_active=True,
        )
        db_session.add(event_type)
        db_session.commit()

        client = Client(
            phone_e164="+85212345679",
            name="John",
            conversation_state=states.AWAITING_DURATION,
        )
        update_conversation_data(
            client,
            book_by_name=True,
            selected_therapist_id=therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_duration(client, "1", db_session)

        assert next_state == states.AWAITING_BY_NAME_DURATION_OPTIONS
        assert "available durations" in response.lower()
        conv_data = json.loads(client.conversation_data or "{}")
        options = conv_data.get("by_name_duration_options")
        assert isinstance(options, list)
        assert len(options) == 1
        assert options[0]["duration_minutes"] == 30

    def test_by_name_duration_option_choice_completes_booking(self, db_session, mock_send_whatsapp):
        """Selecting an available by-name fallback duration should complete booking and reset state."""
        user = User(
            neon_auth_sub="auth-by-name-complete",
            email="by-name-complete@test.com",
            display_name="Dr. Complete",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        therapist = Therapist(user_id=user.id, display_name="Dr. Complete", is_active=True)
        db_session.add(therapist)
        db_session.commit()
        db_session.refresh(therapist)

        client = Client(
            phone_e164="+85212345668",
            name="John",
            conversation_state=states.AWAITING_BY_NAME_DURATION_OPTIONS,
            conversation_data=json.dumps(
                {
                    "book_by_name": True,
                    "selected_therapist_id": therapist.id,
                    "by_name_duration_therapist_id": therapist.id,
                    "by_name_duration_options": [
                        {
                            "duration_minutes": 30,
                            "scheduling_url": "https://calendly.com/dr-complete/30min",
                        }
                    ],
                }
            ),
        )
        db_session.add(client)
        db_session.commit()

        next_state, _ = handle_awaiting_by_name_duration_options(client, "1", db_session)

        assert next_state == states.IDLE
        db_session.refresh(client)
        assert client.conversation_data is None
        assert client.preferred_therapist_id == therapist.id


class TestHandleAwaitingMatchPreference:
    """Tests for handle_awaiting_match_preference function."""

    def test_female_option_sets_prefer_female(self, db_session):
        """Choice 1 should set prefer_female=True with no specialty_id."""
        client = Client(
            phone_e164="+85212345677",
            name="John",
            conversation_state=states.AWAITING_MATCH_PREFERENCE,
        )
        update_conversation_data(client, duration=45)
        db_session.add(client)
        db_session.commit()

        next_state, _ = handle_awaiting_match_preference(client, "1", db_session)

        assert next_state == states.AWAITING_TIME_BAND
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("prefer_female") is True
        assert conv_data.get("specialty_id") is None
        assert conv_data.get("require_specialty") is False

    def test_womens_health_option_sets_specialty(self, db_session):
        """Choice 2 should set Women's Health specialty and require_specialty=True."""
        womens_health = TherapistSpecialty(name="Women's Health", is_active=True)
        db_session.add(womens_health)
        db_session.commit()
        db_session.refresh(womens_health)

        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_MATCH_PREFERENCE,
        )
        update_conversation_data(client, duration=30)
        db_session.add(client)
        db_session.commit()

        next_state, _ = handle_awaiting_match_preference(client, "2", db_session)

        assert next_state == states.AWAITING_TIME_BAND
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("prefer_female") is False
        assert conv_data.get("specialty_id") == womens_health.id
        assert conv_data.get("require_specialty") is True

    def test_no_preference_clears_filters(self, db_session):
        """Choice 3 should clear preference flags."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_MATCH_PREFERENCE,
        )
        update_conversation_data(client, duration=30, prefer_female=True, specialty_id=999)
        db_session.add(client)
        db_session.commit()

        next_state, _ = handle_awaiting_match_preference(client, "3", db_session)

        assert next_state == states.AWAITING_TIME_BAND
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("prefer_female") is False
        assert conv_data.get("specialty_id") is None
        assert conv_data.get("require_specialty") is False

    def test_invalid_choice_rejects(self, db_session):
        """Invalid choice should be rejected."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_MATCH_PREFERENCE,
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_match_preference(client, "99", db_session)

        assert next_state == states.AWAITING_MATCH_PREFERENCE
        assert "please reply" in response.lower()


class TestHandleAwaitingTimeBand:
    """Tests for handle_awaiting_time_band function."""

    def test_choice_1_saves_weekday_day(self, db_session, sample_therapist):
        """Choice 1 should save weekday-day time band."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_TIME_BAND,
        )
        update_conversation_data(client, duration=30, specialty_id=1)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_time_band(client, "1", db_session)

        assert next_state == states.AWAITING_MATCH_CONFIRM
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("time_band") == states.TIME_BAND_WEEKDAY_DAY

    def test_choice_2_saves_weekday_evening(self, db_session, sample_therapist):
        """Choice 2 should save weekday-evening time band."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_TIME_BAND,
        )
        update_conversation_data(client, duration=30, specialty_id=1)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_time_band(client, "2", db_session)

        assert next_state == states.AWAITING_MATCH_CONFIRM
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("time_band") == states.TIME_BAND_WEEKDAY_EVENING

    def test_choice_3_saves_weekend(self, db_session, sample_therapist):
        """Choice 3 should save weekend time band."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_TIME_BAND,
        )
        update_conversation_data(client, duration=30, specialty_id=1)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_time_band(client, "3", db_session)

        assert next_state == states.AWAITING_MATCH_CONFIRM
        conv_data = json.loads(client.conversation_data or "{}")
        assert conv_data.get("time_band") == states.TIME_BAND_WEEKEND


class TestHandleAwaitingTimeBandInvalid:
    """Tests for handle_awaiting_time_band — invalid input."""

    def test_invalid_choice_4_rejects(self, db_session):
        """Out-of-range choice should be rejected with re-prompt."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_TIME_BAND,
        )
        update_conversation_data(client, duration=30, specialty_id=1)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_time_band(client, "4", db_session)

        assert next_state == states.AWAITING_TIME_BAND
        assert "1" in response and "2" in response and "3" in response

    def test_invalid_choice_0_rejects(self, db_session):
        """Zero should be rejected."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_TIME_BAND,
        )
        update_conversation_data(client, duration=30, specialty_id=1)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_time_band(client, "0", db_session)

        assert next_state == states.AWAITING_TIME_BAND

    def test_invalid_text_rejects(self, db_session):
        """Non-numeric text should be rejected."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_TIME_BAND,
        )
        update_conversation_data(client, duration=30, specialty_id=1)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_time_band(client, "help", db_session)

        assert next_state == states.AWAITING_TIME_BAND
        assert "didn't understand" in response.lower()

    def test_multiple_numbers_rejects(self, db_session):
        """Multiple-number input should be rejected for single-choice step."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_TIME_BAND,
        )
        update_conversation_data(client, duration=30, specialty_id=1)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_time_band(client, "1,2", db_session)

        assert next_state == states.AWAITING_TIME_BAND
        assert "1" in response and "2" in response and "3" in response


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
            client, duration=30, specialty_id=1, time_band=states.TIME_BAND_WEEKDAY_DAY
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
            client, duration=30, specialty_id=1, time_band=states.TIME_BAND_WEEKDAY_DAY
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

        assert next_state == states.AWAITING_BOOKING_PATH
        assert client.conversation_data is None  # Reset


class TestHandleAwaitingMatchConfirmInvalid:
    """Tests for handle_awaiting_match_confirm — invalid input."""

    def test_invalid_choice_3_rejects(self, db_session, sample_therapist):
        """Out-of-range choice should be rejected with re-prompt."""
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

        next_state, response = handle_awaiting_match_confirm(client, "3", db_session)

        assert next_state == states.AWAITING_MATCH_CONFIRM
        assert "1" in response and "2" in response

    def test_invalid_text_rejects(self, db_session, sample_therapist):
        """Non-numeric text should be rejected."""
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

        next_state, response = handle_awaiting_match_confirm(client, "help", db_session)

        assert next_state == states.AWAITING_MATCH_CONFIRM
        assert "didn't understand" in response.lower()


class TestCheckGlobalKeywords:
    """Tests for check_global_keywords — works from any conversation state."""

    def test_greeting_from_idle_shows_main_menu(self, db_session):
        """Greeting keyword from IDLE shows main menu."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        result = check_global_keywords(client, "hi", db_session)

        assert result is not None
        next_state, response = result
        assert next_state == states.IDLE
        assert "John" in response
        assert "book" in response.lower()

    def test_greeting_from_mid_flow_resets_to_menu(self, db_session):
        """Greeting keyword mid-flow resets conversation and shows menu."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_MATCH_PREFERENCE,
            conversation_data='{"duration": 30}',
        )
        db_session.add(client)
        db_session.commit()

        result = check_global_keywords(client, "menu", db_session)

        assert result is not None
        next_state, response = result
        assert next_state == states.IDLE
        assert client.conversation_data is None

    def test_all_greeting_keywords_recognized(self, db_session):
        """All greeting keywords should be recognized."""
        for keyword in ["hi", "hello", "hey", "menu", "reset", "start"]:
            client = Client(
                phone_e164=f"+8521234{keyword}",
                name="John",
                conversation_state=states.AWAITING_DURATION,
            )
            db_session.add(client)
            db_session.commit()

            result = check_global_keywords(client, keyword, db_session)
            assert result is not None, f"Keyword '{keyword}' not recognized"
            assert result[0] == states.IDLE

    def test_book_keyword_with_name_starts_booking(self, db_session):
        """'book' keyword for named client goes to duration selection."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        result = check_global_keywords(client, "book", db_session)

        assert result is not None
        next_state, response = result
        assert next_state == states.AWAITING_BOOKING_PATH
        assert "John" in response

    def test_book_keyword_without_name_asks_for_name(self, db_session):
        """'book' keyword for new client goes to name collection."""
        client = Client(
            phone_e164="+85212345678",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        result = check_global_keywords(client, "book", db_session)

        assert result is not None
        next_state, response = result
        assert next_state == states.AWAITING_NAME
        assert "name" in response.lower()

    def test_reschedule_keyword_from_any_state(self, db_session):
        """'reschedule' keyword should work from any state."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_TIME_BAND,
            conversation_data='{"duration": 30}',
        )
        db_session.add(client)
        db_session.commit()

        result = check_global_keywords(client, "reschedule", db_session)

        assert result is not None
        next_state, response = result
        assert next_state == states.IDLE
        assert "appointment" in response.lower()

    def test_cancel_keyword_triggers_reschedule(self, db_session):
        """'cancel' keyword should trigger reschedule flow."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        result = check_global_keywords(client, "cancel", db_session)

        assert result is not None
        next_state, response = result
        assert next_state == states.IDLE
        assert "appointment" in response.lower()

    def test_non_keyword_returns_none(self, db_session):
        """Non-keyword input should return None for normal handler dispatch."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
        )
        db_session.add(client)
        db_session.commit()

        result = check_global_keywords(client, "1", db_session)
        assert result is None

    def test_greeting_shows_preferred_therapist_in_menu(
        self, db_session, sample_therapist
    ):
        """Greeting for client with preferred therapist shows therapist name in menu."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.IDLE,
            preferred_therapist_id=sample_therapist.id,
        )
        db_session.add(client)
        db_session.commit()

        result = check_global_keywords(client, "hello", db_session)

        assert result is not None
        next_state, response = result
        assert next_state == states.IDLE
        assert sample_therapist.display_name in response


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


class TestMatchPreferenceEdgeCases:
    """Tests for edge cases in match-preference step."""

    def test_womens_health_missing_returns_to_main_menu(self, db_session):
        """Missing Women's Health specialty should return to main menu."""
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_MATCH_PREFERENCE,
        )
        update_conversation_data(client, duration=30)
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_match_preference(client, "2", db_session)

        assert next_state == states.IDLE
        assert "women's health" in response.lower()
        assert "book" in response.lower()


class TestNoTherapistMatch:
    """Tests for edge case when no therapists match."""

    def test_days_handler_resets_when_no_therapists(self, db_session):
        """Days handler should reset to IDLE when no active therapists exist."""
        # No therapists seeded
        client = Client(
            phone_e164="+85212345678",
            name="John",
            conversation_state=states.AWAITING_DAYS,
        )
        update_conversation_data(
            client, duration=30, specialty_id=1, time_band=states.TIME_BAND_WEEKDAY_DAY
        )
        db_session.add(client)
        db_session.commit()

        next_state, response = handle_awaiting_days(client, "1", db_session)

        assert next_state == states.IDLE
        assert "couldn't find an available therapist" in response.lower()
        assert client.conversation_data is None

