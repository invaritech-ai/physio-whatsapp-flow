from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.models import BillingPlan, ClientPlanAssignment, Session as TherapySession

SUPPORTED_PLAN_DURATIONS = {30, 45}


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


def resolve_expected_charge(
    session: TherapySession,
    *,
    plan_map: dict[tuple[int, int], dict[str, Any]],
) -> tuple[int | None, str | None, dict[str, Any] | None]:
    """Resolve expected pricing context for a session."""
    assigned_plan = plan_map.get((session.client_id, session.duration_minutes))
    if assigned_plan:
        return assigned_plan["amount_cents"], assigned_plan["currency"], assigned_plan

    if session.charge_amount_cents is not None:
        return session.charge_amount_cents, session.currency, None

    return None, session.currency, None
