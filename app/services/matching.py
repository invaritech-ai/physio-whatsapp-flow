"""Therapist matching engine with 4-factor scoring and fallback cascade."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlmodel import Session, func, select

from app.core.config import settings
from app.core.encryption import decrypt_string
from app.models import (
    MatchingDecision,
    Session as TherapySession,
    Therapist,
    TherapistEventType,
    TherapistSpecialty,
    TherapistSpecialtyMap,
)
from app.services.calendly import get_event_type_available_times_with_pat

# Scoring weights — well-separated so higher-priority factors always dominate
WEIGHT_SPECIALTY = 100
WEIGHT_CONTINUITY = 30
WEIGHT_TIME_BAND = 10
WEIGHT_LOAD_MAX = 9  # max load bonus (0 sessions = 9 points)

TIME_BAND_WEEKDAY_DAY = "weekday_day"
TIME_BAND_WEEKDAY_EVENING = "weekday_evening"
TIME_BAND_WEEKEND = "weekend"

# Fallback cascade configuration
FALLBACK_LEVELS = [
    {"specialty_required": True, "time_band_required": True},  # Level 0
    {"specialty_required": True, "time_band_required": False},  # Level 1
    {"specialty_required": False, "time_band_required": True},  # Level 2
    {"specialty_required": False, "time_band_required": False},  # Level 3
]


@dataclass
class MatchResult:
    """Result of the matching engine."""

    therapist: Therapist
    fallback_level: int
    rationale: str
    scoring_breakdown: list[dict]


def match_therapist(
    db: Session,
    client_id: int,
    specialty_id: int | None,
    duration: int,
    time_band: str | None,
    preferred_days: list[int] | None,
    preferred_therapist_id: int | None = None,
    exclude_therapist_id: int | None = None,
) -> MatchResult | None:
    """
    Run 4-factor scoring engine with fallback cascade.

    Returns MatchResult or None if no active therapists exist.
    Persists a MatchingDecision audit row for every call.
    """
    # Get all active therapists
    therapists = list(
        db.exec(
            select(Therapist)
            .where(Therapist.is_active == True)  # noqa: E712
            .order_by(Therapist.id)
        ).all()
    )

    # Remove excluded therapist (e.g. "different therapist" flow)
    if exclude_therapist_id is not None:
        therapists = [t for t in therapists if t.id != exclude_therapist_id]

    # Resolve specialty name for audit
    specialty_name = None
    if specialty_id is not None:
        specialty = db.exec(
            select(TherapistSpecialty).where(TherapistSpecialty.id == specialty_id)
        ).first()
        specialty_name = specialty.name if specialty else None

    # No active therapists — persist audit and return None
    if not therapists:
        _persist_audit(
            db=db,
            client_id=client_id,
            duration=duration,
            specialty_name=specialty_name,
            time_band=time_band,
            days=preferred_days,
            selected_therapist_id=None,
            scoring_breakdown=[],
            rationale="No active therapists available.",
            fallback_level=3,
        )
        return None

    # Get specialty therapist IDs
    specialty_therapist_ids = _get_specialty_therapist_ids(db, specialty_id)

    normalized_time_band = _normalize_time_band(time_band)
    time_band_map = _get_therapist_time_band_matches(
        db=db,
        therapists=therapists,
        duration=duration,
        requested_time_band=normalized_time_band,
    )

    # Get load for all active therapists
    therapist_ids = [t.id for t in therapists]
    load_map = _get_therapist_load(db, therapist_ids)

    # Score all therapists (for the full breakdown)
    all_scores = []
    for t in therapists:
        score = _score_therapist(
            therapist=t,
            specialty_therapist_ids=specialty_therapist_ids,
            preferred_therapist_id=preferred_therapist_id,
            load=load_map.get(t.id, 0),
            time_band_match=time_band_map.get(t.id),
        )
        all_scores.append(score)

    # Run fallback cascade
    for level, criteria in enumerate(FALLBACK_LEVELS):
        candidates = _filter_candidates(
            therapists=therapists,
            scores=all_scores,
            specialty_therapist_ids=specialty_therapist_ids,
            specialty_id=specialty_id,
            specialty_required=criteria["specialty_required"],
            time_band_required=criteria["time_band_required"],
            requested_time_band=normalized_time_band,
        )

        if candidates:
            # Sort by total_score descending, then by therapist ID ascending for determinism
            candidates.sort(key=lambda c: (-c[1]["total_score"], c[0].id))
            winner, winner_score = candidates[0]

            # Mark the selected therapist in breakdown
            breakdown = _mark_selected(all_scores, winner.id)

            rationale = _build_rationale(
                therapist=winner,
                specialty_name=specialty_name,
                fallback_level=level,
                has_continuity=winner_score["continuity_match"],
            )

            _persist_audit(
                db=db,
                client_id=client_id,
                duration=duration,
                specialty_name=specialty_name,
                time_band=time_band,
                days=preferred_days,
                selected_therapist_id=winner.id,
                scoring_breakdown=breakdown,
                rationale=rationale,
                fallback_level=level,
            )

            return MatchResult(
                therapist=winner,
                fallback_level=level,
                rationale=rationale,
                scoring_breakdown=breakdown,
            )

    # Should not reach here (level 3 has no filters), but handle gracefully
    _persist_audit(
        db=db,
        client_id=client_id,
        duration=duration,
        specialty_name=specialty_name,
        time_band=time_band,
        days=preferred_days,
        selected_therapist_id=None,
        scoring_breakdown=_mark_selected(all_scores, None),
        rationale="No therapists matched after exhausting all fallback levels.",
        fallback_level=3,
    )
    return None


def _get_specialty_therapist_ids(db: Session, specialty_id: int | None) -> set[int]:
    """Get IDs of therapists who have the given specialty."""
    if specialty_id is None:
        return set()

    rows = db.exec(
        select(TherapistSpecialtyMap.therapist_id).where(
            TherapistSpecialtyMap.specialty_id == specialty_id
        )
    ).all()
    return set(rows)


def _get_therapist_load(db: Session, therapist_ids: list[int]) -> dict[int, int]:
    """Count non-cancelled sessions in the next 7 days per therapist."""
    if not therapist_ids:
        return {}

    now = datetime.now(timezone.utc)
    week_later = now + timedelta(days=7)

    rows = db.exec(
        select(TherapySession.therapist_id, func.count(TherapySession.id))
        .where(
            TherapySession.therapist_id.in_(therapist_ids),  # type: ignore[union-attr]
            TherapySession.status != "cancelled",
            TherapySession.start_time >= now,
            TherapySession.start_time < week_later,
        )
        .group_by(TherapySession.therapist_id)
    ).all()

    return {therapist_id: count for therapist_id, count in rows}


def _score_therapist(
    therapist: Therapist,
    specialty_therapist_ids: set[int],
    preferred_therapist_id: int | None,
    load: int,
    time_band_match: bool | None,
) -> dict:
    """Compute per-therapist score breakdown."""
    has_specialty = therapist.id in specialty_therapist_ids
    has_continuity = preferred_therapist_id is not None and therapist.id == preferred_therapist_id

    specialty_score = WEIGHT_SPECIALTY if has_specialty else 0
    continuity_score = WEIGHT_CONTINUITY if has_continuity else 0
    time_band_score = WEIGHT_TIME_BAND if time_band_match is True else 0
    load_score = max(0, WEIGHT_LOAD_MAX - load)

    total = specialty_score + continuity_score + time_band_score + load_score

    return {
        "therapist_id": therapist.id,
        "therapist_name": therapist.display_name,
        "total_score": total,
        "specialty_match": has_specialty,
        "specialty_score": specialty_score,
        "continuity_match": has_continuity,
        "continuity_score": continuity_score,
        "time_band_match": time_band_match,
        "time_band_score": time_band_score,
        "upcoming_sessions": load,
        "load_score": load_score,
        "selected": False,  # Will be set later by _mark_selected
    }


def _filter_candidates(
    therapists: list[Therapist],
    scores: list[dict],
    specialty_therapist_ids: set[int],
    specialty_id: int | None,
    specialty_required: bool,
    time_band_required: bool,
    requested_time_band: str | None,
) -> list[tuple[Therapist, dict]]:
    """Filter therapists based on fallback level criteria."""
    candidates = []
    for therapist, score in zip(therapists, scores):
        # Specialty filter
        if specialty_required and specialty_id is not None:
            if therapist.id not in specialty_therapist_ids:
                continue

        # Time-band filter:
        # - apply only when user gave a supported time-band preference
        # - fail only when we explicitly know therapist has no slots in that band
        if time_band_required and requested_time_band is not None:
            if score.get("time_band_match") is False:
                continue

        candidates.append((therapist, score))
    return candidates


def _normalize_time_band(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("-", "_")
    mapping = {
        TIME_BAND_WEEKDAY_DAY: TIME_BAND_WEEKDAY_DAY,
        "day": TIME_BAND_WEEKDAY_DAY,
        "morning": TIME_BAND_WEEKDAY_DAY,
        "afternoon": TIME_BAND_WEEKDAY_DAY,
        TIME_BAND_WEEKDAY_EVENING: TIME_BAND_WEEKDAY_EVENING,
        "evening": TIME_BAND_WEEKDAY_EVENING,
        TIME_BAND_WEEKEND: TIME_BAND_WEEKEND,
        "weekend": TIME_BAND_WEEKEND,
    }
    return mapping.get(normalized)


def _therapist_zone(therapist: Therapist) -> ZoneInfo:
    tz_name = therapist.preferred_timezone or settings.invoice_timezone or "UTC"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _parse_slot_start(slot: dict) -> datetime | None:
    raw = slot.get("start_time")
    if not isinstance(raw, str):
        return None
    candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bucket_for_local_time(local_start: datetime) -> str | None:
    weekday = local_start.weekday()
    hour = local_start.hour
    if weekday >= 5:
        return TIME_BAND_WEEKEND
    if 9 <= hour < 17:
        return TIME_BAND_WEEKDAY_DAY
    if hour >= 17:
        return TIME_BAND_WEEKDAY_EVENING
    return None


def _get_therapist_time_band_matches(
    *,
    db: Session,
    therapists: list[Therapist],
    duration: int,
    requested_time_band: str | None,
) -> dict[int, bool | None]:
    """Return per-therapist time-band match from Calendly available slots.

    `True`  -> explicitly has at least one available slot in requested band
    `False` -> explicitly checked and none matched
    `None`  -> not evaluated (missing PAT/event type or provider failure)
    """
    result: dict[int, bool | None] = {}
    if requested_time_band is None:
        return result

    start_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    end_time = start_time + timedelta(days=7)

    for therapist in therapists:
        therapist_id = therapist.id
        if therapist_id is None:
            continue

        event_type = db.exec(
            select(TherapistEventType).where(
                TherapistEventType.therapist_id == therapist_id,
                TherapistEventType.duration_minutes == duration,
                TherapistEventType.is_active == True,  # noqa: E712
            )
        ).first()
        if not event_type or not therapist.calendly_pat_encrypted:
            result[therapist_id] = None
            continue

        try:
            calendly_pat = decrypt_string(therapist.calendly_pat_encrypted)
            available_slots = get_event_type_available_times_with_pat(
                event_type_uri=event_type.calendly_event_type_uri,
                calendly_pat=calendly_pat,
                start_time=start_time,
                end_time=end_time,
            )
        except Exception:
            result[therapist_id] = None
            continue

        zone = _therapist_zone(therapist)
        has_match = False
        for slot in available_slots:
            if not isinstance(slot, dict):
                continue
            slot_start = _parse_slot_start(slot)
            if slot_start is None:
                continue
            local_start = slot_start.astimezone(zone)
            if _bucket_for_local_time(local_start) == requested_time_band:
                has_match = True
                break
        result[therapist_id] = has_match

    return result


def _mark_selected(scores: list[dict], winner_id: int | None) -> list[dict]:
    """Return a copy of scores with selected=True on the winner."""
    result = []
    for score in scores:
        entry = dict(score)
        entry["selected"] = entry["therapist_id"] == winner_id
        result.append(entry)
    return result


def _build_rationale(
    therapist: Therapist,
    specialty_name: str | None,
    fallback_level: int,
    has_continuity: bool,
) -> str:
    """Build a one-line rationale string."""
    name = therapist.display_name

    if fallback_level <= 1 and specialty_name:
        parts = [f"Matched {specialty_name} specialist {name}"]
        extras = []
        if has_continuity:
            extras.append("continuity bonus")
        extras.append("low load")
        if fallback_level == 1:
            extras.append("time preference relaxed")
        parts.append(f" ({', '.join(extras)}).")
        return "".join(parts)

    if fallback_level == 2:
        return f"Matched {name} (specialty relaxed, low load)."

    # Level 3 or no specialty
    return f"Matched {name} (any available therapist, lowest load)."


def _persist_audit(
    db: Session,
    client_id: int,
    duration: int,
    specialty_name: str | None,
    time_band: str | None,
    days: list[int] | None,
    selected_therapist_id: int | None,
    scoring_breakdown: list[dict],
    rationale: str,
    fallback_level: int,
) -> MatchingDecision:
    """Create and persist a MatchingDecision audit row."""
    decision = MatchingDecision(
        client_id=client_id,
        requested_duration=duration,
        requested_specialty=specialty_name,
        requested_time_band=time_band,
        requested_days=json.dumps(days) if days is not None else None,
        selected_therapist_id=selected_therapist_id,
        scoring_breakdown=json.dumps(scoring_breakdown),
        rationale=rationale,
        fallback_level=fallback_level,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision
