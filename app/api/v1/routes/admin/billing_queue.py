"""Admin billing queue endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.v1.schemas.billing import BillingQueueItem, BillingQueueResponse
from app.core.auth import get_current_admin
from app.db.session import get_session
from app.models import User
from app.services.billing_queue import QuickRange, _quick_range_bounds, get_billing_queue_optimized
from app.services.pricing import (
    load_active_plan_map,
    resolve_expected_charge,
)
from app.services.timezone_utils import normalize_query_datetime, to_preferred_timezone

router = APIRouter(prefix="/admin/billing", tags=["Admin - Billing Queue"])


@router.get("/queue", response_model=BillingQueueResponse)
def get_billing_queue(
    quick_range: QuickRange = Query(default="14d"),
    statuses: list[str] | None = Query(default=None),
    needs_confirmation: bool | None = None,
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    preferred_timezone = admin.preferred_timezone
    default_statuses = {"started", "completed"}
    status_set = {s.strip() for s in statuses if s.strip()} if statuses else default_statuses

    from_bound = normalize_query_datetime(from_date)
    to_bound = normalize_query_datetime(to_date)
    if from_bound is None and to_bound is None:
        from_bound, to_bound = _quick_range_bounds(quick_range)

    raw_items, total = get_billing_queue_optimized(
        db,
        status_set=status_set,
        from_bound=from_bound,
        to_bound=to_bound,
        needs_confirmation=needs_confirmation,
        limit=limit,
        offset=offset,
    )

    if not raw_items:
        return BillingQueueResponse(items=[], total=0, limit=limit, offset=offset, has_more=False)

    client_ids = {item["client_id"] for item in raw_items}
    plan_map = load_active_plan_map(db, client_ids=client_ids)

    items: list[BillingQueueItem] = []
    for row in raw_items:
        session_id = row["session_id"]
        client_id = row["client_id"]
        duration = row["duration_minutes"]

        class _SessionStub:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        stub_session = _SessionStub(
            client_id=client_id,
            therapist_id=row["therapist_id"],
            duration_minutes=duration,
            charge_amount_cents=None,
            currency=row["currency"],
        )
        expected_charge_cents, _, assigned_plan = resolve_expected_charge(
            stub_session, plan_map=plan_map
        )
        expected_charge_cents = (
            expected_charge_cents
            if expected_charge_cents is not None
            else int(assigned_plan["amount_cents"]) if assigned_plan else None
        )

        items.append(
            BillingQueueItem(
                session_id=session_id,
                client_id=client_id,
                client_name=row["client_name"],
                therapist_id=row["therapist_id"],
                therapist_name=row["therapist_name"],
                start_time=to_preferred_timezone(row["start_time"], preferred_timezone),
                end_time=to_preferred_timezone(row["end_time"], preferred_timezone),
                duration_minutes=duration,
                status=row["status"],
                currency=row["currency"],
                expected_charge_cents=expected_charge_cents,
                paid_cents=row["paid_cents"],
                receipted_cents=row["receipted_cents"],
                outstanding_cents=row["outstanding_cents"],
                needs_confirmation=row["needs_confirmation"],
                default_receipt_amount_cents=row["default_receipt_amount_cents"],
                last_payment_at=(
                    to_preferred_timezone(row["last_payment_at"], preferred_timezone)
                    if isinstance(row["last_payment_at"], datetime)
                    else None
                ),
                last_receipt_at=(
                    to_preferred_timezone(row["last_receipt_at"], preferred_timezone)
                    if isinstance(row["last_receipt_at"], datetime)
                    else None
                ),
            )
        )

    has_more = (offset + len(items)) < total
    return BillingQueueResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )
