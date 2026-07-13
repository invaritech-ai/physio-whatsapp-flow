"""Admin reporting endpoints (utilization + payroll aggregates)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func
from sqlmodel import Session, select

from app.api.v1.schemas.reports import (
    TherapistPayrollDetailResponse,
    TherapistPayrollDetailSessionItem,
    TherapistPayrollItem,
    TherapistPayrollListResponse,
    TherapistUtilizationItem,
    TherapistUtilizationListResponse,
)
from app.core.auth import get_current_admin
from app.core.config import settings
from app.db.session import get_session
from app.models import Client, Session as TherapySession, Therapist, User
from app.services.payroll import load_therapist_payout_map

router = APIRouter(prefix="/admin/reports", tags=["Admin - Reports"])


def _validate_period(*, period_from: datetime, period_to: datetime) -> None:
    if period_from >= period_to:
        raise HTTPException(status_code=400, detail="Invalid range: 'from' must be before 'to'.")


def _has_more(*, total: int, limit: int, offset: int) -> bool:
    return offset + limit < total


@router.get("/therapist-utilization", response_model=TherapistUtilizationListResponse)
def list_therapist_utilization(
    period_from: datetime = Query(alias="from"),
    period_to: datetime = Query(alias="to"),
    therapist_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    _validate_period(period_from=period_from, period_to=period_to)

    stmt = (
        select(
            Therapist.id,
            Therapist.display_name,
            func.sum(case((TherapySession.status == "completed", 1), else_=0)),
            func.sum(case((TherapySession.status == "scheduled", 1), else_=0)),
            func.sum(case((TherapySession.status == "cancelled", 1), else_=0)),
            func.sum(case((TherapySession.status == "no_show", 1), else_=0)),
            func.sum(
                case(
                    (TherapySession.status.in_(["started", "completed"]), TherapySession.duration_minutes),
                    else_=0,
                )
            ),
        )
        .select_from(TherapySession)
        .join(Therapist, Therapist.id == TherapySession.therapist_id)
        .where(
            TherapySession.start_time >= period_from,
            TherapySession.start_time <= period_to,
        )
        .group_by(Therapist.id, Therapist.display_name)
        .order_by(func.coalesce(Therapist.display_name, ""), Therapist.id.asc())
    )
    if therapist_id is not None:
        stmt = stmt.where(TherapySession.therapist_id == therapist_id)

    rows = list(db.exec(stmt).all())
    items = [
        TherapistUtilizationItem(
            therapist_id=int(row[0]),
            therapist_name=row[1] or f"Therapist #{row[0]}",
            completed_sessions=int(row[2] or 0),
            scheduled_sessions=int(row[3] or 0),
            cancelled_sessions=int(row[4] or 0),
            no_show_sessions=int(row[5] or 0),
            utilized_minutes=int(row[6] or 0),
            period_start=period_from,
            period_end=period_to,
        )
        for row in rows
    ]

    total = len(items)
    page = items[offset : offset + limit]
    return TherapistUtilizationListResponse(
        items=page,
        total=total,
        limit=limit,
        offset=offset,
        has_more=_has_more(total=total, limit=limit, offset=offset),
    )


@router.get("/therapist-payroll", response_model=TherapistPayrollListResponse)
def list_therapist_payroll_summary(
    period_from: datetime = Query(alias="from"),
    period_to: datetime = Query(alias="to"),
    therapist_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    _validate_period(period_from=period_from, period_to=period_to)

    # Start from Therapist with an OUTER JOIN so every therapist is listed, even
    # those with no sessions in the period. Date filters live in the JOIN condition
    # (a WHERE on session columns would drop therapists with no in-range sessions).
    stmt = (
        select(
            Therapist.id,
            Therapist.display_name,
            func.sum(case((TherapySession.status == "completed", 1), else_=0)),
            func.sum(
                case(
                    (TherapySession.status == "completed", TherapySession.duration_minutes),
                    else_=0,
                )
            ),
        )
        .select_from(Therapist)
        .join(
            TherapySession,
            and_(
                TherapySession.therapist_id == Therapist.id,
                TherapySession.start_time >= period_from,
                TherapySession.start_time <= period_to,
            ),
            isouter=True,
        )
        .group_by(Therapist.id, Therapist.display_name)
        .order_by(func.coalesce(Therapist.display_name, ""), Therapist.id.asc())
    )
    if therapist_id is not None:
        stmt = stmt.where(Therapist.id == therapist_id)

    rows = list(db.exec(stmt).all())

    # Completed sessions grouped by (therapist, duration) → counts, to apply the
    # configured per-duration payout for each therapist.
    dur_stmt = (
        select(
            TherapySession.therapist_id,
            TherapySession.duration_minutes,
            func.count(),
        )
        .where(
            TherapySession.status == "completed",
            TherapySession.start_time >= period_from,
            TherapySession.start_time <= period_to,
        )
        .group_by(TherapySession.therapist_id, TherapySession.duration_minutes)
    )
    if therapist_id is not None:
        dur_stmt = dur_stmt.where(TherapySession.therapist_id == therapist_id)

    counts_by_therapist: dict[int, dict[int, int]] = {}
    for tid, duration, count in db.exec(dur_stmt).all():
        counts_by_therapist.setdefault(int(tid), {})[int(duration)] = int(count)

    payout_map = load_therapist_payout_map(
        db, therapist_ids={int(row[0]) for row in rows}
    )

    def _estimated_pay(tid: int) -> int:
        return sum(
            count * payout_map.get((tid, duration), 0)
            for duration, count in counts_by_therapist.get(tid, {}).items()
        )

    items = [
        TherapistPayrollItem(
            therapist_id=int(row[0]),
            therapist_name=row[1] or f"Therapist #{row[0]}",
            completed_sessions=int(row[2] or 0),
            payable_minutes=int(row[3] or 0),
            estimated_payable_cents=_estimated_pay(int(row[0])),
            currency=settings.default_currency,
            period_start=period_from,
            period_end=period_to,
        )
        for row in rows
    ]

    total = len(items)
    page = items[offset : offset + limit]
    return TherapistPayrollListResponse(
        items=page,
        total=total,
        limit=limit,
        offset=offset,
        has_more=_has_more(total=total, limit=limit, offset=offset),
    )


@router.get("/therapist-payroll/{therapist_id}", response_model=TherapistPayrollDetailResponse)
def get_therapist_payroll_detail(
    therapist_id: int,
    period_from: datetime = Query(alias="from"),
    period_to: datetime = Query(alias="to"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Per-therapist payroll: each completed session in range with its payout + totals."""
    _ = admin
    _validate_period(period_from=period_from, period_to=period_to)

    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=404, detail="Therapist not found")

    payout_map = load_therapist_payout_map(db, therapist_ids={therapist_id})

    rows = db.exec(
        select(TherapySession, Client.name)
        .join(Client, Client.id == TherapySession.client_id, isouter=True)
        .where(
            TherapySession.therapist_id == therapist_id,
            TherapySession.status == "completed",
            TherapySession.start_time >= period_from,
            TherapySession.start_time <= period_to,
        )
        .order_by(TherapySession.start_time.asc())
    ).all()

    sessions: list[TherapistPayrollDetailSessionItem] = []
    total_minutes = 0
    total_pay = 0
    for session, client_name in rows:
        payout = payout_map.get((therapist_id, session.duration_minutes), 0)
        total_minutes += session.duration_minutes
        total_pay += payout
        sessions.append(
            TherapistPayrollDetailSessionItem(
                session_id=session.id,
                client_name=client_name,
                start_time=session.start_time,
                duration_minutes=session.duration_minutes,
                payout_cents=payout,
                currency=settings.default_currency,
            )
        )

    return TherapistPayrollDetailResponse(
        therapist_id=therapist_id,
        therapist_name=therapist.display_name or f"Therapist #{therapist_id}",
        period_start=period_from,
        period_end=period_to,
        currency=settings.default_currency,
        total_sessions=len(sessions),
        total_minutes=total_minutes,
        total_pay_cents=total_pay,
        sessions=sessions,
    )
