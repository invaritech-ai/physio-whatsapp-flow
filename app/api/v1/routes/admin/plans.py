"""Admin endpoints for billing plan catalog and client plan assignments."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.api.v1.schemas.billing import (
    BillingPlanCreate,
    BillingPlanResponse,
    BillingPlanUpdate,
    ClientPlanAssignmentSummary,
    ClientPlanAssignmentsResponse,
    ClientPlanAssignmentsUpsertRequest,
)
from app.core.auth import get_current_admin
from app.db.session import get_session
from app.models import BillingPlan, Client, ClientPlanAssignment, User
from app.services.pricing import SUPPORTED_PLAN_DURATIONS, load_active_plan_map

router = APIRouter(prefix="/admin", tags=["Admin - Plans"])


def _ensure_client_exists(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="client_not_found")
    return client


def _ensure_plan_exists(db: Session, plan_id: int) -> BillingPlan:
    plan = db.get(BillingPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="plan_not_found")
    return plan


def _to_plan_response(plan: BillingPlan) -> BillingPlanResponse:
    return BillingPlanResponse(
        id=plan.id,
        name=plan.name,
        duration_minutes=plan.duration_minutes,
        amount_cents=plan.amount_cents,
        currency=plan.currency,
        is_active=plan.is_active,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _build_client_assignment_response(
    *,
    client_id: int,
    plan_map: dict[tuple[int, int], dict[str, object]],
) -> ClientPlanAssignmentsResponse:
    assignments: dict[str, ClientPlanAssignmentSummary | None] = {}
    for duration in SUPPORTED_PLAN_DURATIONS:
        raw = plan_map.get((client_id, duration))
        assignments[str(duration)] = ClientPlanAssignmentSummary(**raw) if raw else None
    return ClientPlanAssignmentsResponse(client_id=client_id, assignments=assignments)


@router.get("/plans", response_model=list[BillingPlanResponse])
def list_plans(
    duration_minutes: int | None = Query(default=None),
    is_active: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    stmt = select(BillingPlan)
    if duration_minutes is not None:
        if duration_minutes not in SUPPORTED_PLAN_DURATIONS:
            raise HTTPException(status_code=400, detail="unsupported_duration")
        stmt = stmt.where(BillingPlan.duration_minutes == duration_minutes)
    if is_active is not None:
        stmt = stmt.where(BillingPlan.is_active == is_active)
    stmt = stmt.order_by(BillingPlan.duration_minutes.asc(), BillingPlan.amount_cents.asc())
    rows = db.exec(stmt.offset(offset).limit(limit)).all()
    return [_to_plan_response(plan) for plan in rows]


@router.post("/plans", response_model=BillingPlanResponse, status_code=201)
def create_plan(
    payload: BillingPlanCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    now = datetime.now(timezone.utc)
    plan = BillingPlan(
        name=payload.name.strip(),
        duration_minutes=payload.duration_minutes,
        amount_cents=payload.amount_cents,
        currency=payload.currency.upper(),
        is_active=payload.is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _to_plan_response(plan)


@router.patch("/plans/{plan_id}", response_model=BillingPlanResponse)
def update_plan(
    plan_id: int,
    payload: BillingPlanUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    plan = _ensure_plan_exists(db, plan_id)
    if "name" in payload.model_fields_set and payload.name is not None:
        plan.name = payload.name.strip()
    if "duration_minutes" in payload.model_fields_set and payload.duration_minutes is not None:
        plan.duration_minutes = payload.duration_minutes
    if "amount_cents" in payload.model_fields_set and payload.amount_cents is not None:
        plan.amount_cents = payload.amount_cents
    if "currency" in payload.model_fields_set and payload.currency is not None:
        plan.currency = payload.currency.upper()
    if "is_active" in payload.model_fields_set and payload.is_active is not None:
        plan.is_active = payload.is_active
    plan.updated_at = datetime.now(timezone.utc)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _to_plan_response(plan)


@router.get("/clients/{client_id}/plans", response_model=ClientPlanAssignmentsResponse)
def get_client_plans(
    client_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    _ensure_client_exists(db, client_id)
    plan_map = load_active_plan_map(db, client_ids={client_id})
    return _build_client_assignment_response(client_id=client_id, plan_map=plan_map)


@router.put("/clients/{client_id}/plans", response_model=ClientPlanAssignmentsResponse)
def upsert_client_plans(
    client_id: int,
    payload: ClientPlanAssignmentsUpsertRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    if admin.id is None:
        raise HTTPException(status_code=403, detail="access_denied")
    _ensure_client_exists(db, client_id)
    now = datetime.now(timezone.utc)

    assignment_by_duration = {item.duration_minutes: item for item in payload.assignments}
    for duration, item in assignment_by_duration.items():
        existing = db.exec(
            select(ClientPlanAssignment).where(
                ClientPlanAssignment.client_id == client_id,
                ClientPlanAssignment.duration_minutes == duration,
            )
        ).first()

        if item.billing_plan_id is None or item.is_active is False:
            if existing:
                db.delete(existing)
            continue

        plan = _ensure_plan_exists(db, item.billing_plan_id)
        if plan.duration_minutes != duration:
            raise HTTPException(status_code=400, detail="plan_duration_mismatch")

        if existing:
            existing.billing_plan_id = item.billing_plan_id
            existing.assigned_by_user_id = admin.id
            existing.effective_from = item.effective_from or now
            existing.notes = item.notes
            existing.is_active = True
            existing.updated_at = now
            db.add(existing)
        else:
            db.add(
                ClientPlanAssignment(
                    client_id=client_id,
                    duration_minutes=duration,
                    billing_plan_id=item.billing_plan_id,
                    assigned_by_user_id=admin.id,
                    effective_from=item.effective_from or now,
                    notes=item.notes,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )

    db.commit()
    plan_map = load_active_plan_map(db, client_ids={client_id})
    return _build_client_assignment_response(client_id=client_id, plan_map=plan_map)
