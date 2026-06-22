from __future__ import annotations

from sqlmodel import Session, select

from app.models import TherapistEventType


def load_therapist_payout_map(
    db: Session,
    *,
    therapist_ids: set[int],
) -> dict[tuple[int, int], int]:
    """Return configured therapist payouts keyed by (therapist_id, duration_minutes).

    Only active event types that have a payout set are included. Drives payroll:
    a completed session pays the therapist the payout for its duration.
    """
    if not therapist_ids:
        return {}

    rows = db.exec(
        select(TherapistEventType).where(
            TherapistEventType.therapist_id.in_(therapist_ids),  # type: ignore[arg-type]
            TherapistEventType.is_active == True,  # noqa: E712
            TherapistEventType.payout_cents.is_not(None),  # type: ignore[union-attr]
        )
    ).all()

    mapping: dict[tuple[int, int], int] = {}
    for et in rows:
        key = (et.therapist_id, et.duration_minutes)
        if key not in mapping and et.payout_cents is not None:
            mapping[key] = et.payout_cents
    return mapping
