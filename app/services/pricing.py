from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    BillingPlan,
    ClientPlanAssignment,
    Session as TherapySession,
    TherapistEventType,
)

# Ordered tuple: drives plan-side validation and deterministic ordering of
# duration-keyed responses. Plans/billing/payroll support these durations.
SUPPORTED_PLAN_DURATIONS = (15, 30, 45, 60)


def load_active_plan_map(
    db: Session,
    *,
    client_ids: set[int],
) -> dict[tuple[int, int], dict[str, Any]]:
    """Return active plan assignments keyed by (client_id, duration_minutes)."""
    if not client_ids:
        return {}

    rows = db.exec(
        select(ClientPlanAssignment, BillingPlan)
        .join(BillingPlan, BillingPlan.id == ClientPlanAssignment.billing_plan_id)
        .where(
            ClientPlanAssignment.client_id.in_(client_ids),  # type: ignore[arg-type]
            ClientPlanAssignment.is_active == True,  # noqa: E712
            BillingPlan.is_active == True,  # noqa: E712
        )
        .order_by(
            ClientPlanAssignment.client_id,
            ClientPlanAssignment.duration_minutes,
            ClientPlanAssignment.effective_from.desc(),
            ClientPlanAssignment.updated_at.desc(),
        )
    ).all()

    mapping: dict[tuple[int, int], dict[str, Any]] = {}
    for assignment, plan in rows:
        key = (assignment.client_id, assignment.duration_minutes)
        if key in mapping:
            continue
        mapping[key] = {
            "plan_id": plan.id,
            "plan_name": plan.name,
            "duration_minutes": assignment.duration_minutes,
            "amount_cents": plan.amount_cents,
            "currency": plan.currency,
            "effective_from": assignment.effective_from,
            "notes": assignment.notes,
            "is_active": assignment.is_active,
        }
    return mapping


def load_therapist_slot_price_map(
    db: Session,
    *,
    therapist_ids: set[int],
) -> dict[tuple[int, int], dict[str, Any]]:
    """Return per-therapist slot prices keyed by (therapist_id, duration_minutes).

    Only active event types that have a price set are included.
    """
    if not therapist_ids:
        return {}

    rows = db.exec(
        select(TherapistEventType).where(
            TherapistEventType.therapist_id.in_(therapist_ids),  # type: ignore[arg-type]
            TherapistEventType.is_active == True,  # noqa: E712
            TherapistEventType.amount_cents.is_not(None),  # type: ignore[union-attr]
        )
    ).all()

    mapping: dict[tuple[int, int], dict[str, Any]] = {}
    for et in rows:
        key = (et.therapist_id, et.duration_minutes)
        if key in mapping:
            continue
        mapping[key] = {
            "amount_cents": et.amount_cents,
            "currency": et.currency or settings.default_currency,
        }
    return mapping


def resolve_expected_charge(
    session: TherapySession,
    *,
    plan_map: dict[tuple[int, int], dict[str, Any]],
    slot_price_map: dict[tuple[int, int], dict[str, Any]] | None = None,
) -> tuple[int | None, str | None, dict[str, Any] | None]:
    """Resolve expected pricing context for a session.

    Precedence: therapist per-slot price > client billing plan >
    session.charge_amount_cents > none. The third tuple element is always the
    client's assigned plan context (or None) regardless of which price won.
    """
    assigned_plan = plan_map.get((session.client_id, session.duration_minutes))

    if slot_price_map:
        slot = slot_price_map.get((session.therapist_id, session.duration_minutes))
        if slot and slot.get("amount_cents") is not None:
            return slot["amount_cents"], slot.get("currency") or session.currency, assigned_plan

    if assigned_plan:
        return assigned_plan["amount_cents"], assigned_plan["currency"], assigned_plan

    if session.charge_amount_cents is not None:
        return session.charge_amount_cents, session.currency, None

    return None, session.currency, None
