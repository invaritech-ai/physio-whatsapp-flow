"""Admin action-center summary endpoint."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_
from sqlmodel import Session, select

from app.api.v1.schemas.action_center import (
    AdminActionCenterDebugIds,
    AdminActionCenterSummaryResponse,
)
from app.core.auth import get_current_admin
from app.db.session import get_session
from app.models import (
    AccessRequest,
    AuthEvent,
    ClientFinancial,
    ClientPlanAssignment,
    PaymentRecord,
    Session as TherapySession,
    Therapist,
    TherapistSpecialtyMap,
    User,
)
from app.services.pricing import SUPPORTED_PLAN_DURATIONS

router = APIRouter(prefix="/admin/action-center", tags=["Admin - Action Center"])


@router.get("/summary", response_model=AdminActionCenterSummaryResponse)
def get_action_center_summary(
    lookback_days: int = Query(default=30, ge=1, le=365),
    financial_alert_threshold_cents: int = Query(default=100000, ge=1),
    include_debug_ids: bool = Query(default=False),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=lookback_days)

    pending_access_requests = db.exec(
        select(func.count())
        .select_from(AccessRequest)
        .where(AccessRequest.status == "pending")
    ).one()

    therapists_missing_license = db.exec(
        select(func.count())
        .select_from(Therapist)
        .where(
            or_(
                Therapist.license_number.is_(None),
                func.trim(Therapist.license_number) == "",
            )
        )
    ).one()

    therapists_missing_calendly = db.exec(
        select(func.count())
        .select_from(Therapist)
        .where(
            or_(
                Therapist.calendly_user_uri.is_(None),
                func.trim(Therapist.calendly_user_uri) == "",
            )
        )
    ).one()

    specialty_exists = (
        select(TherapistSpecialtyMap.id)
        .where(TherapistSpecialtyMap.therapist_id == Therapist.id)
        .exists()
    )
    therapists_missing_specialties = db.exec(
        select(func.count()).select_from(Therapist).where(~specialty_exists)
    ).one()

    active_clients_subquery = (
        select(TherapySession.client_id.label("client_id"))
        .where(TherapySession.start_time >= window_start)
        .distinct()
        .subquery()
    )

    active_clients_in_window = db.exec(
        select(func.count()).select_from(active_clients_subquery)
    ).one()

    def _missing_plan_count_query(duration: int):
        return (
            select(func.count())
            .select_from(active_clients_subquery)
            .outerjoin(
                ClientPlanAssignment,
                and_(
                    ClientPlanAssignment.client_id == active_clients_subquery.c.client_id,
                    ClientPlanAssignment.duration_minutes == duration,
                    ClientPlanAssignment.is_active == True,  # noqa: E712
                ),
            )
            .where(ClientPlanAssignment.id.is_(None))
        )

    clients_missing_plan_by_duration = {
        str(duration): db.exec(_missing_plan_count_query(duration)).one()
        for duration in SUPPORTED_PLAN_DURATIONS
    }

    def _assignment_exists(duration: int):
        return (
            select(ClientPlanAssignment.id)
            .where(
                and_(
                    ClientPlanAssignment.client_id == active_clients_subquery.c.client_id,
                    ClientPlanAssignment.duration_minutes == duration,
                    ClientPlanAssignment.is_active == True,  # noqa: E712
                )
            )
            .exists()
        )

    active_clients_missing_any_plan_assignment = db.exec(
        select(func.count())
        .select_from(active_clients_subquery)
        .where(or_(*[~_assignment_exists(d) for d in SUPPORTED_PLAN_DURATIONS]))
    ).one()

    clients_with_receipting_backlog = db.exec(
        select(func.count())
        .select_from(ClientFinancial)
        .where(
            (ClientFinancial.total_paid_cents - ClientFinancial.total_receipted_cents)
            >= financial_alert_threshold_cents
        )
    ).one()

    past_sessions_missing_payment_record = db.exec(
        select(func.count(func.distinct(TherapySession.id)))
        .select_from(TherapySession)
        .outerjoin(PaymentRecord, PaymentRecord.session_id == TherapySession.id)
        .where(
            TherapySession.end_time < now,
            TherapySession.end_time >= window_start,
            TherapySession.status.notin_(["cancelled", "no_show"]),
            PaymentRecord.id.is_(None),
        )
    ).one()

    active_clients_missing_financial_profile = db.exec(
        select(func.count())
        .select_from(active_clients_subquery)
        .outerjoin(
            ClientFinancial,
            ClientFinancial.client_id == active_clients_subquery.c.client_id,
        )
        .where(ClientFinancial.id.is_(None))
    ).one()

    # Untriaged appointment-change notifications, so cancellations/reschedules reach the
    # dashboard bell instead of only the Notifications page (req 2.9). Queue status lives
    # in the JSON blob, matched here as a substring to keep this one cheap COUNT.
    # ponytail: couples to json.dumps' default spacing — promote queue_status to a real
    # indexed column if this needs sorting/filtering rather than counting.
    def _pending_queue_count(admin_event_type: str) -> int:
        return db.exec(
            select(func.count())
            .select_from(AuthEvent)
            .where(
                AuthEvent.event_type == admin_event_type,
                AuthEvent.details_json.like('%"queue_status": "new"%'),  # type: ignore[union-attr]
            )
        ).one()

    appointment_cancellations_pending_review = _pending_queue_count(
        "admin.calendly.queue.invitee.canceled"
    )
    appointment_reschedules_pending_review = _pending_queue_count(
        "admin.calendly.queue.invitee.rescheduled"
    )

    debug_ids: AdminActionCenterDebugIds | None = None
    if include_debug_ids:
        pending_access_request_ids = db.exec(
            select(AccessRequest.id)
            .where(AccessRequest.status == "pending")
            .order_by(AccessRequest.requested_at.desc(), AccessRequest.id.desc())
        ).all()
        def _missing_plan_ids_query(duration: int):
            return (
                select(active_clients_subquery.c.client_id)
                .outerjoin(
                    ClientPlanAssignment,
                    and_(
                        ClientPlanAssignment.client_id == active_clients_subquery.c.client_id,
                        ClientPlanAssignment.duration_minutes == duration,
                        ClientPlanAssignment.is_active == True,  # noqa: E712
                    ),
                )
                .where(ClientPlanAssignment.id.is_(None))
                .order_by(active_clients_subquery.c.client_id)
            )

        clients_missing_plan_ids_by_duration = {
            str(duration): list(db.exec(_missing_plan_ids_query(duration)).all())
            for duration in SUPPORTED_PLAN_DURATIONS
        }
        clients_missing_any_plan_assignment_ids = sorted(
            {
                client_id
                for ids in clients_missing_plan_ids_by_duration.values()
                for client_id in ids
            }
        )
        past_sessions_missing_payment_record_ids = db.exec(
            select(func.distinct(TherapySession.id))
            .select_from(TherapySession)
            .outerjoin(PaymentRecord, PaymentRecord.session_id == TherapySession.id)
            .where(
                TherapySession.end_time < now,
                TherapySession.end_time >= window_start,
                TherapySession.status.notin_(["cancelled", "no_show"]),
                PaymentRecord.id.is_(None),
            )
            .order_by(TherapySession.id)
        ).all()
        active_clients_missing_financial_profile_ids = db.exec(
            select(active_clients_subquery.c.client_id)
            .outerjoin(
                ClientFinancial,
                ClientFinancial.client_id == active_clients_subquery.c.client_id,
            )
            .where(ClientFinancial.id.is_(None))
            .order_by(active_clients_subquery.c.client_id)
        ).all()
        debug_ids = AdminActionCenterDebugIds(
            pending_access_request_ids=pending_access_request_ids,
            clients_missing_plan_ids_by_duration=clients_missing_plan_ids_by_duration,
            clients_missing_any_plan_assignment_ids=clients_missing_any_plan_assignment_ids,
            past_sessions_missing_payment_record_ids=past_sessions_missing_payment_record_ids,
            active_clients_missing_financial_profile_ids=active_clients_missing_financial_profile_ids,
        )

    return AdminActionCenterSummaryResponse(
        as_of=now,
        lookback_days=lookback_days,
        financial_alert_threshold_cents=financial_alert_threshold_cents,
        active_clients_in_window=active_clients_in_window,
        pending_access_requests=pending_access_requests,
        therapists_missing_license=therapists_missing_license,
        therapists_missing_calendly=therapists_missing_calendly,
        therapists_missing_specialties=therapists_missing_specialties,
        clients_missing_plan_by_duration=clients_missing_plan_by_duration,
        active_clients_missing_any_plan_assignment=active_clients_missing_any_plan_assignment,
        clients_with_receipting_backlog=clients_with_receipting_backlog,
        past_sessions_missing_payment_record=past_sessions_missing_payment_record,
        active_clients_missing_financial_profile=active_clients_missing_financial_profile,
        appointment_cancellations_pending_review=appointment_cancellations_pending_review,
        appointment_reschedules_pending_review=appointment_reschedules_pending_review,
        debug_ids=debug_ids,
    )
