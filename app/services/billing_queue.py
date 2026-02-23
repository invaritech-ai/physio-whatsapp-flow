"""Optimized billing queue service with single-query approach."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import case, func, select
from sqlalchemy.orm import aliased
from sqlmodel import Session

from app.models import (
    Client,
    PaymentRecord,
    Receipt,
    Session as TherapySession,
    Therapist,
)

QuickRange = Literal["today", "7d", "14d", "30d", "all"]


def _quick_range_bounds(quick_range: QuickRange) -> tuple[datetime | None, datetime | None]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if quick_range == "all":
        return None, None
    if quick_range == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start, end

    days_map = {
        "7d": 7,
        "14d": 14,
        "30d": 30,
    }
    days = days_map[quick_range]
    start = now - timedelta(days=days)
    return start, now


def get_billing_queue_optimized(
    db: Session,
    *,
    status_set: set[str],
    from_bound: datetime | None,
    to_bound: datetime | None,
    needs_confirmation: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """
    Get billing queue with a single optimized query.
    
    Uses subqueries for payment/receipt aggregation and window functions
    for efficient pagination with accurate total count.
    
    Returns:
        Tuple of (items, total_count)
    """
    paid_subq = (
        select(
            PaymentRecord.session_id,
            func.coalesce(func.sum(PaymentRecord.amount_cents), 0).label("paid_cents"),
            func.max(func.coalesce(PaymentRecord.paid_at, PaymentRecord.created_at)).label("last_payment_at"),
        )
        .where(PaymentRecord.status == "confirmed")
        .group_by(PaymentRecord.session_id)
        .subquery()
    )

    receipt_subq = (
        select(
            Receipt.session_id,
            func.coalesce(func.sum(Receipt.amount_cents), 0).label("receipted_cents"),
            func.max(Receipt.created_at).label("last_receipt_at"),
        )
        .where(Receipt.status == "issued")
        .group_by(Receipt.session_id)
        .subquery()
    )

    outstanding_expr = func.coalesce(paid_subq.c.paid_cents, 0) - func.coalesce(receipt_subq.c.receipted_cents, 0)
    needs_confirmation_expr = case(
        (outstanding_expr > 0, True),
        else_=False,
    )

    sort_needs_confirmation = case(
        (needs_confirmation_expr == True, 0),
        else_=1,
    )

    query = (
        select(
            TherapySession.id.label("session_id"),
            TherapySession.client_id,
            TherapySession.therapist_id,
            TherapySession.start_time,
            TherapySession.end_time,
            TherapySession.duration_minutes,
            TherapySession.status,
            TherapySession.currency,
            Client.name.label("client_name"),
            Client.default_receipt_amount_cents,
            Therapist.display_name.label("therapist_name"),
            func.coalesce(paid_subq.c.paid_cents, 0).label("paid_cents"),
            func.coalesce(receipt_subq.c.receipted_cents, 0).label("receipted_cents"),
            outstanding_expr.label("outstanding_cents"),
            needs_confirmation_expr.label("needs_confirmation"),
            paid_subq.c.last_payment_at,
            receipt_subq.c.last_receipt_at,
        )
        .select_from(TherapySession)
        .outerjoin(paid_subq, paid_subq.c.session_id == TherapySession.id)
        .outerjoin(receipt_subq, receipt_subq.c.session_id == TherapySession.id)
        .outerjoin(Client, Client.id == TherapySession.client_id)
        .outerjoin(Therapist, Therapist.id == TherapySession.therapist_id)
        .where(TherapySession.status.in_(status_set))
    )

    if from_bound is not None:
        query = query.where(TherapySession.start_time >= from_bound)
    if to_bound is not None:
        query = query.where(TherapySession.start_time <= to_bound)
    if needs_confirmation is not None:
        query = query.where(needs_confirmation_expr == needs_confirmation)

    count_query = select(func.count()).select_from(query.subquery())
    total = db.exec(count_query).scalar() or 0

    query = query.order_by(
        sort_needs_confirmation.asc(),
        TherapySession.start_time.asc(),
        outstanding_expr.desc(),
        TherapySession.id.asc(),
    )

    query = query.offset(offset).limit(limit)

    results = db.exec(query).all()

    items = []
    for row in results:
        items.append({
            "session_id": row.session_id,
            "client_id": row.client_id,
            "client_name": row.client_name,
            "therapist_id": row.therapist_id,
            "therapist_name": row.therapist_name,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "duration_minutes": row.duration_minutes,
            "status": row.status,
            "currency": row.currency,
            "paid_cents": int(row.paid_cents or 0),
            "receipted_cents": int(row.receipted_cents or 0),
            "outstanding_cents": int(row.outstanding_cents or 0),
            "needs_confirmation": bool(row.needs_confirmation),
            "default_receipt_amount_cents": row.default_receipt_amount_cents,
            "last_payment_at": row.last_payment_at,
            "last_receipt_at": row.last_receipt_at,
        })

    return items, total


def get_session_financial_summary(
    db: Session,
    session_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """
    Get financial summary for specific sessions.
    Used for batch lookups when expected charge resolution is needed.
    """
    if not session_ids:
        return {}

    paid_rows = db.exec(
        select(
            PaymentRecord.session_id,
            func.coalesce(func.sum(PaymentRecord.amount_cents), 0),
            func.max(func.coalesce(PaymentRecord.paid_at, PaymentRecord.created_at)),
        )
        .where(
            PaymentRecord.session_id.in_(session_ids),
            PaymentRecord.status == "confirmed",
        )
        .group_by(PaymentRecord.session_id)
    ).all()

    receipt_rows = db.exec(
        select(
            Receipt.session_id,
            func.coalesce(func.sum(Receipt.amount_cents), 0),
            func.max(Receipt.created_at),
        )
        .where(
            Receipt.session_id.in_(session_ids),
            Receipt.status == "issued",
        )
        .group_by(Receipt.session_id)
    ).all()

    result = {}
    for session_id in session_ids:
        result[session_id] = {
            "paid_cents": 0,
            "receipted_cents": 0,
            "last_payment_at": None,
            "last_receipt_at": None,
        }

    for row in paid_rows:
        result[row[0]]["paid_cents"] = int(row[1] or 0)
        result[row[0]]["last_payment_at"] = row[2]

    for row in receipt_rows:
        result[row[0]]["receipted_cents"] = int(row[1] or 0)
        result[row[0]]["last_receipt_at"] = row[2]

    return result
