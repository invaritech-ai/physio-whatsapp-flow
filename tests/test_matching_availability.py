"""Availability-aware matching tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from app.models import TherapistEventType, TherapistSpecialtyMap
from app.services.matching import match_therapist
from tests.test_matching import _create_therapist


def _assign_specialty(db_session, therapist_id: int, specialty_id: int) -> None:
    db_session.add(
        TherapistSpecialtyMap(
            therapist_id=therapist_id,
            specialty_id=specialty_id,
        )
    )
    db_session.commit()


def _add_event_type(
    db_session,
    *,
    therapist_id: int,
    duration_minutes: int,
    uri_suffix: str,
) -> TherapistEventType:
    event_type = TherapistEventType(
        therapist_id=therapist_id,
        calendly_event_type_uri=f"https://api.calendly.com/event_types/{uri_suffix}",
        duration_minutes=duration_minutes,
        scheduling_url=f"https://calendly.com/test/{uri_suffix}",
        is_active=True,
    )
    db_session.add(event_type)
    db_session.commit()
    db_session.refresh(event_type)
    return event_type


def test_match_uses_real_time_band_slot_signal(db_session, sample_client, sample_specialties):
    t_day = _create_therapist(db_session, "Day", 2001)
    t_evening = _create_therapist(db_session, "Evening", 2002)
    t_day.preferred_timezone = "Asia/Hong_Kong"
    t_evening.preferred_timezone = "Asia/Hong_Kong"
    t_day.calendly_pat_encrypted = "enc-day"
    t_evening.calendly_pat_encrypted = "enc-evening"
    db_session.add(t_day)
    db_session.add(t_evening)
    db_session.commit()

    _assign_specialty(db_session, t_day.id, sample_specialties[0].id)
    _assign_specialty(db_session, t_evening.id, sample_specialties[0].id)
    et_day = _add_event_type(db_session, therapist_id=t_day.id, duration_minutes=45, uri_suffix="day-45")
    et_evening = _add_event_type(
        db_session,
        therapist_id=t_evening.id,
        duration_minutes=45,
        uri_suffix="evening-45",
    )

    def _slot_provider(*, event_type_uri: str, calendly_pat: str, start_time: datetime, end_time: datetime):
        _ = calendly_pat, start_time, end_time
        if event_type_uri == et_day.calendly_event_type_uri:
            # 10:00 HKT => weekday_day
            return [{"start_time": "2026-02-23T02:00:00Z"}]
        if event_type_uri == et_evening.calendly_event_type_uri:
            # 18:30 HKT => weekday_evening
            return [{"start_time": "2026-02-23T10:30:00Z"}]
        return []

    with (
        patch("app.services.matching.decrypt_string", return_value="plain-pat"),
        patch(
            "app.services.matching.get_event_type_available_times_with_pat",
            side_effect=_slot_provider,
        ),
    ):
        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=45,
            time_band="weekday_day",
            preferred_days=[1],
        )

    assert result is not None
    assert result.therapist.id == t_day.id
    day_entry = next(e for e in result.scoring_breakdown if e["therapist_id"] == t_day.id)
    evening_entry = next(e for e in result.scoring_breakdown if e["therapist_id"] == t_evening.id)
    assert day_entry["time_band_match"] is True
    assert day_entry["time_band_score"] > 0
    assert evening_entry["time_band_match"] is False


def test_match_falls_back_when_time_band_has_no_slots(db_session, sample_client, sample_specialties):
    therapist = _create_therapist(db_session, "OnlyEvening", 3001)
    therapist.preferred_timezone = "Asia/Hong_Kong"
    therapist.calendly_pat_encrypted = "enc-only"
    db_session.add(therapist)
    db_session.commit()

    _assign_specialty(db_session, therapist.id, sample_specialties[0].id)
    event_type = _add_event_type(
        db_session,
        therapist_id=therapist.id,
        duration_minutes=30,
        uri_suffix="only-evening-30",
    )

    with (
        patch("app.services.matching.decrypt_string", return_value="plain-pat"),
        patch(
            "app.services.matching.get_event_type_available_times_with_pat",
            return_value=[{"start_time": "2026-02-23T10:30:00Z"}],  # 18:30 HKT
        ),
    ):
        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="weekday_day",
            preferred_days=[1],
        )

    assert event_type is not None
    assert result is not None
    assert result.therapist.id == therapist.id
    # Level 0 requires time-band match; level 1 relaxes it.
    assert result.fallback_level == 1
