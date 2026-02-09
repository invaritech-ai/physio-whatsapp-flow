"""Unit tests for therapist matching engine."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.models import (
    Client,
    MatchingDecision,
    Session as TherapySession,
    Therapist,
    TherapistSpecialty,
    TherapistSpecialtyMap,
    User,
)
from app.services.matching import MatchResult, match_therapist


def _create_therapist(db_session, name: str, index: int) -> Therapist:
    """Helper to create a User + Therapist pair."""
    user = User(
        neon_auth_sub=f"auth-{index}",
        email=f"therapist{index}@test.com",
        display_name=f"Dr. {name}",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name=f"Dr. {name}",
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return therapist


def _create_session(
    db_session, therapist_id: int, client_id: int, days_from_now: int = 1, status: str = "scheduled"
) -> TherapySession:
    """Helper to create a Session for load testing."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=days_from_now)
    session = TherapySession(
        client_id=client_id,
        therapist_id=therapist_id,
        start_time=start,
        end_time=start + timedelta(minutes=30),
        duration_minutes=30,
        status=status,
        source="manual",
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


def _assign_specialty(db_session, therapist_id: int, specialty_id: int) -> TherapistSpecialtyMap:
    """Helper to create a specialty assignment."""
    mapping = TherapistSpecialtyMap(
        therapist_id=therapist_id,
        specialty_id=specialty_id,
    )
    db_session.add(mapping)
    db_session.commit()
    return mapping


class TestMatchTherapistBasic:
    """Basic matching scenarios."""

    def test_single_therapist_with_specialty_returns_level_0(self, db_session, sample_client, sample_specialties):
        """One therapist with matching specialty -> level 0 match."""
        therapist = _create_therapist(db_session, "Smith", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1, 2, 3],
        )

        assert result is not None
        assert result.therapist.id == therapist.id
        assert result.fallback_level == 0

    def test_single_therapist_without_specialty_falls_back(self, db_session, sample_client, sample_specialties):
        """One therapist without matching specialty -> fallback level 2+."""
        therapist = _create_therapist(db_session, "Smith", 1)
        # No specialty assigned

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        assert result.therapist.id == therapist.id
        assert result.fallback_level >= 2

    def test_no_active_therapists_returns_none(self, db_session, sample_client, sample_specialties):
        """No active therapists -> returns None."""
        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is None

    def test_inactive_therapist_excluded(self, db_session, sample_client, sample_specialties):
        """Inactive therapist should not be matched."""
        therapist = _create_therapist(db_session, "Smith", 1)
        therapist.is_active = False
        db_session.add(therapist)
        db_session.commit()
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is None


class TestMatchTherapistSpecialtyScoring:
    """Specialty match is the primary scoring factor."""

    def test_specialty_therapist_beats_non_specialty(self, db_session, sample_client, sample_specialties):
        """Therapist with matching specialty wins over one without."""
        t_no_spec = _create_therapist(db_session, "NoSpec", 1)
        t_with_spec = _create_therapist(db_session, "WithSpec", 2)
        _assign_specialty(db_session, t_with_spec.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        assert result.therapist.id == t_with_spec.id
        assert result.fallback_level == 0

    def test_multiple_specialty_therapists_all_scored(self, db_session, sample_client, sample_specialties):
        """When multiple therapists have the specialty, all appear in breakdown."""
        t1 = _create_therapist(db_session, "A", 1)
        t2 = _create_therapist(db_session, "B", 2)
        _assign_specialty(db_session, t1.id, sample_specialties[0].id)
        _assign_specialty(db_session, t2.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        # Both therapists should be in the breakdown
        breakdown_ids = {entry["therapist_id"] for entry in result.scoring_breakdown}
        assert t1.id in breakdown_ids
        assert t2.id in breakdown_ids


class TestMatchTherapistContinuityBonus:
    """Continuity bonus for returning clients."""

    def test_preferred_therapist_gets_continuity_bonus(self, db_session, sample_client, sample_specialties):
        """Client's preferred therapist should get higher score."""
        t1 = _create_therapist(db_session, "Regular", 1)
        t2 = _create_therapist(db_session, "Preferred", 2)
        _assign_specialty(db_session, t1.id, sample_specialties[0].id)
        _assign_specialty(db_session, t2.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
            preferred_therapist_id=t2.id,
        )

        assert result is not None
        assert result.therapist.id == t2.id

        # Check scoring breakdown shows continuity bonus
        preferred_entry = next(e for e in result.scoring_breakdown if e["therapist_id"] == t2.id)
        regular_entry = next(e for e in result.scoring_breakdown if e["therapist_id"] == t1.id)
        assert preferred_entry["continuity_match"] is True
        assert preferred_entry["continuity_score"] > 0
        assert regular_entry["continuity_match"] is False

    def test_continuity_does_not_override_specialty(self, db_session, sample_client, sample_specialties):
        """Non-specialty therapist with continuity should lose to specialty therapist without."""
        t_spec = _create_therapist(db_session, "Specialist", 1)
        t_cont = _create_therapist(db_session, "Preferred", 2)
        _assign_specialty(db_session, t_spec.id, sample_specialties[0].id)
        # t_cont has no specialty but is preferred

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
            preferred_therapist_id=t_cont.id,
        )

        assert result is not None
        assert result.therapist.id == t_spec.id

    def test_continuity_within_specialty_wins(self, db_session, sample_client, sample_specialties):
        """Among specialty therapists, preferred one wins."""
        t1 = _create_therapist(db_session, "Regular", 1)
        t2 = _create_therapist(db_session, "Preferred", 2)
        _assign_specialty(db_session, t1.id, sample_specialties[0].id)
        _assign_specialty(db_session, t2.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
            preferred_therapist_id=t2.id,
        )

        assert result is not None
        assert result.therapist.id == t2.id
        assert result.fallback_level == 0


class TestMatchTherapistLoadTiebreaker:
    """Lower load (fewer upcoming sessions) breaks ties."""

    def test_lower_load_therapist_wins_tie(self, db_session, sample_client, sample_specialties):
        """Between equal therapists, one with fewer sessions wins."""
        t_busy = _create_therapist(db_session, "Busy", 1)
        t_free = _create_therapist(db_session, "Free", 2)
        _assign_specialty(db_session, t_busy.id, sample_specialties[0].id)
        _assign_specialty(db_session, t_free.id, sample_specialties[0].id)

        # Give t_busy 3 upcoming sessions
        for i in range(3):
            _create_session(db_session, t_busy.id, sample_client.id, days_from_now=i + 1)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        assert result.therapist.id == t_free.id

    def test_load_excludes_cancelled_sessions(self, db_session, sample_client, sample_specialties):
        """Cancelled sessions should not count toward load."""
        t1 = _create_therapist(db_session, "T1", 1)
        t2 = _create_therapist(db_session, "T2", 2)
        _assign_specialty(db_session, t1.id, sample_specialties[0].id)
        _assign_specialty(db_session, t2.id, sample_specialties[0].id)

        # t1 has 3 cancelled sessions (shouldn't count)
        for i in range(3):
            _create_session(db_session, t1.id, sample_client.id, days_from_now=i + 1, status="cancelled")

        # t2 has 1 real session
        _create_session(db_session, t2.id, sample_client.id, days_from_now=1)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        # t1 has 0 real load, t2 has 1 → t1 wins (lower ID breaks further tie)
        assert result.therapist.id == t1.id

    def test_load_counts_only_next_7_days(self, db_session, sample_client, sample_specialties):
        """Sessions beyond 7 days should not count toward load."""
        t_far = _create_therapist(db_session, "FarSessions", 1)
        t_near = _create_therapist(db_session, "NearSessions", 2)
        _assign_specialty(db_session, t_far.id, sample_specialties[0].id)
        _assign_specialty(db_session, t_near.id, sample_specialties[0].id)

        # t_far has sessions 10 days out (shouldn't count)
        for i in range(5):
            _create_session(db_session, t_far.id, sample_client.id, days_from_now=10 + i)

        # t_near has 1 session within 7 days
        _create_session(db_session, t_near.id, sample_client.id, days_from_now=2)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        # t_far has 0 load (beyond window), t_near has 1 → t_far wins
        assert result.therapist.id == t_far.id

    def test_zero_load_gets_max_score(self, db_session, sample_client, sample_specialties):
        """Therapist with no upcoming sessions gets maximum load bonus."""
        therapist = _create_therapist(db_session, "Free", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        entry = result.scoring_breakdown[0]
        assert entry["upcoming_sessions"] == 0
        assert entry["load_score"] == 9  # WEIGHT_LOAD_MAX


class TestMatchTherapistFallbackCascade:
    """Fallback cascade through levels 0-3."""

    def test_level_0_full_match(self, db_session, sample_client, sample_specialties):
        """Level 0: specialty match present, returns level 0."""
        therapist = _create_therapist(db_session, "Smith", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        assert result.fallback_level == 0

    def test_no_specialty_match_falls_to_level_2_or_higher(self, db_session, sample_client, sample_specialties):
        """No therapists with requested specialty -> falls to level 2+."""
        therapist = _create_therapist(db_session, "Smith", 1)
        # Assign a different specialty
        _assign_specialty(db_session, therapist.id, sample_specialties[1].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,  # Request specialty[0], therapist has [1]
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        assert result.therapist.id == therapist.id
        assert result.fallback_level >= 2

    def test_fallback_reports_correct_level(self, db_session, sample_client, sample_specialties):
        """Fallback level in result matches the actual cascade level used."""
        therapist = _create_therapist(db_session, "Smith", 1)
        # No specialty assigned at all

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        # Should be level 2 or 3 (no specialty match)
        assert result.fallback_level >= 2

    def test_no_specialty_id_skips_specialty_filter(self, db_session, sample_client):
        """When specialty_id is None, all therapists are candidates at level 0."""
        therapist = _create_therapist(db_session, "Smith", 1)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=None,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        assert result.therapist.id == therapist.id
        # No specialty to filter on, so should be a low fallback level
        assert result.fallback_level <= 1


class TestMatchTherapistTimeBandDeferred:
    """Time-band factor is deferred — verify it doesn't affect scoring."""

    def test_time_band_param_accepted_but_ignored(self, db_session, sample_client, sample_specialties):
        """time_band param is accepted without error and doesn't affect result."""
        therapist = _create_therapist(db_session, "Smith", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        result_morning = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        result_evening = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="evening",
            preferred_days=[1],
        )

        assert result_morning is not None
        assert result_evening is not None
        assert result_morning.therapist.id == result_evening.therapist.id

    def test_scoring_breakdown_shows_time_band_null(self, db_session, sample_client, sample_specialties):
        """time_band_match in breakdown should be None (not evaluated)."""
        therapist = _create_therapist(db_session, "Smith", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        entry = result.scoring_breakdown[0]
        assert entry["time_band_match"] is None
        assert entry["time_band_score"] == 0


class TestMatchTherapistAuditTrail:
    """MatchingDecision audit row persistence."""

    def test_audit_row_created_on_match(self, db_session, sample_client, sample_specialties):
        """Successful match should persist a MatchingDecision row."""
        therapist = _create_therapist(db_session, "Smith", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1, 3],
        )

        decisions = db_session.exec(select(MatchingDecision)).all()
        assert len(decisions) == 1
        assert decisions[0].selected_therapist_id == therapist.id

    def test_audit_row_created_on_no_match(self, db_session, sample_client, sample_specialties):
        """No match (no therapists) should still persist an audit row."""
        match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        decisions = db_session.exec(select(MatchingDecision)).all()
        assert len(decisions) == 1
        assert decisions[0].selected_therapist_id is None

    def test_audit_contains_correct_inputs(self, db_session, sample_client, sample_specialties):
        """Audit row should have correct requested values."""
        therapist = _create_therapist(db_session, "Smith", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=45,
            time_band="afternoon",
            preferred_days=[1, 3, 5],
        )

        decision = db_session.exec(select(MatchingDecision)).first()
        assert decision is not None
        assert decision.client_id == sample_client.id
        assert decision.requested_duration == 45
        assert decision.requested_specialty == sample_specialties[0].name
        assert decision.requested_time_band == "afternoon"
        assert json.loads(decision.requested_days) == [1, 3, 5]

    def test_audit_contains_scoring_breakdown_json(self, db_session, sample_client, sample_specialties):
        """Audit row scoring_breakdown should be valid JSON with per-therapist details."""
        therapist = _create_therapist(db_session, "Smith", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        decision = db_session.exec(select(MatchingDecision)).first()
        assert decision is not None
        breakdown = json.loads(decision.scoring_breakdown)
        assert isinstance(breakdown, list)
        assert len(breakdown) >= 1
        assert "therapist_id" in breakdown[0]
        assert "total_score" in breakdown[0]

    def test_audit_contains_rationale(self, db_session, sample_client, sample_specialties):
        """Audit row should have a non-empty rationale string."""
        therapist = _create_therapist(db_session, "Smith", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        decision = db_session.exec(select(MatchingDecision)).first()
        assert decision is not None
        assert len(decision.rationale) > 0

    def test_audit_records_fallback_level(self, db_session, sample_client, sample_specialties):
        """Audit row fallback_level should match the result."""
        therapist = _create_therapist(db_session, "Smith", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        decision = db_session.exec(select(MatchingDecision)).first()
        assert decision is not None
        assert decision.fallback_level == result.fallback_level

    def test_audit_selected_therapist_matches_result(self, db_session, sample_client, sample_specialties):
        """Audit selected_therapist_id should match the returned therapist."""
        therapist = _create_therapist(db_session, "Smith", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        decision = db_session.exec(select(MatchingDecision)).first()
        assert decision is not None
        assert decision.selected_therapist_id == result.therapist.id


class TestMatchTherapistDeterminism:
    """Matching should be deterministic for same inputs."""

    def test_tie_broken_by_therapist_id(self, db_session, sample_client, sample_specialties):
        """Equal scores should be resolved by lower therapist ID."""
        t1 = _create_therapist(db_session, "First", 1)
        t2 = _create_therapist(db_session, "Second", 2)
        _assign_specialty(db_session, t1.id, sample_specialties[0].id)
        _assign_specialty(db_session, t2.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        # Lower ID should win when scores are equal
        assert result.therapist.id == min(t1.id, t2.id)


class TestMatchTherapistExclude:
    """Exclude therapist (used when client picks 'different therapist')."""

    def test_excluded_therapist_not_matched(self, db_session, sample_client, sample_specialties):
        """Excluded therapist should never be selected, even if highest scoring."""
        t_preferred = _create_therapist(db_session, "Preferred", 1)
        t_other = _create_therapist(db_session, "Other", 2)
        _assign_specialty(db_session, t_preferred.id, sample_specialties[0].id)
        _assign_specialty(db_session, t_other.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
            preferred_therapist_id=t_preferred.id,
            exclude_therapist_id=t_preferred.id,
        )

        assert result is not None
        assert result.therapist.id == t_other.id

    def test_excluded_therapist_not_in_breakdown(self, db_session, sample_client, sample_specialties):
        """Excluded therapist should not appear in scoring breakdown."""
        t_excluded = _create_therapist(db_session, "Excluded", 1)
        t_other = _create_therapist(db_session, "Other", 2)
        _assign_specialty(db_session, t_excluded.id, sample_specialties[0].id)
        _assign_specialty(db_session, t_other.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
            exclude_therapist_id=t_excluded.id,
        )

        assert result is not None
        breakdown_ids = {entry["therapist_id"] for entry in result.scoring_breakdown}
        assert t_excluded.id not in breakdown_ids

    def test_exclude_only_therapist_returns_none(self, db_session, sample_client, sample_specialties):
        """If the only active therapist is excluded, returns None."""
        therapist = _create_therapist(db_session, "Only", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
            exclude_therapist_id=therapist.id,
        )

        assert result is None

    def test_exclude_none_has_no_effect(self, db_session, sample_client, sample_specialties):
        """exclude_therapist_id=None should not filter anyone."""
        therapist = _create_therapist(db_session, "Smith", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
            exclude_therapist_id=None,
        )

        assert result is not None
        assert result.therapist.id == therapist.id


class TestScoringBreakdownFormat:
    """Verify the scoring_breakdown structure."""

    def test_breakdown_contains_all_active_therapists(self, db_session, sample_client, sample_specialties):
        """All active therapists should appear in breakdown, not just the selected one."""
        t1 = _create_therapist(db_session, "A", 1)
        t2 = _create_therapist(db_session, "B", 2)
        t3 = _create_therapist(db_session, "C", 3)
        _assign_specialty(db_session, t1.id, sample_specialties[0].id)
        # t2, t3 have no specialty

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        breakdown_ids = {entry["therapist_id"] for entry in result.scoring_breakdown}
        assert t1.id in breakdown_ids
        assert t2.id in breakdown_ids
        assert t3.id in breakdown_ids

    def test_breakdown_fields_present(self, db_session, sample_client, sample_specialties):
        """Each entry should have all expected fields."""
        therapist = _create_therapist(db_session, "Smith", 1)
        _assign_specialty(db_session, therapist.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        entry = result.scoring_breakdown[0]
        expected_fields = {
            "therapist_id", "therapist_name", "total_score",
            "specialty_match", "specialty_score",
            "continuity_match", "continuity_score",
            "time_band_match", "time_band_score",
            "upcoming_sessions", "load_score",
            "selected",
        }
        assert expected_fields.issubset(entry.keys())

    def test_selected_flag_on_winner_only(self, db_session, sample_client, sample_specialties):
        """Only the selected therapist should have selected=True."""
        t1 = _create_therapist(db_session, "Winner", 1)
        t2 = _create_therapist(db_session, "Loser", 2)
        _assign_specialty(db_session, t1.id, sample_specialties[0].id)
        _assign_specialty(db_session, t2.id, sample_specialties[0].id)

        result = match_therapist(
            db=db_session,
            client_id=sample_client.id,
            specialty_id=sample_specialties[0].id,
            duration=30,
            time_band="morning",
            preferred_days=[1],
        )

        assert result is not None
        selected_entries = [e for e in result.scoring_breakdown if e["selected"]]
        assert len(selected_entries) == 1
        assert selected_entries[0]["therapist_id"] == result.therapist.id
