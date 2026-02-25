"""Admin reporting endpoints (utilization + payroll aggregates)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlmodel import Session, select

from app.api.v1.schemas.reports import (
    TherapistPayrollItem,
    TherapistPayrollListResponse,
    TherapistUtilizationItem,
    TherapistUtilizationListResponse,
)
from app.core.auth import get_current_admin
from app.core.config import settings
from app.db.session import get_session
from app.models import Session as TherapySession, Therapist, User

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
        TherapistPayrollItem(
            therapist_id=int(row[0]),
            therapist_name=row[1] or f"Therapist #{row[0]}",
            completed_sessions=int(row[2] or 0),
            payable_minutes=int(row[3] or 0),
            # Phase 2 will introduce therapist hourly-rate based payroll math.
            estimated_payable_cents=0,
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
