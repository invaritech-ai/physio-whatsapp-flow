"""Tests for admin action center summary endpoint."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import (
    AccessRequest,
    BillingPlan,
    Client,
    ClientFinancial,
    ClientPlanAssignment,
    Session as TherapySession,
    Therapist,
    TherapistSpecialty,
    TherapistSpecialtyMap,
    User,
)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _create_admin(db_session: Session) -> User:
    admin = User(
        neon_auth_sub="admin-action-center-sub",
        email="admin-action-center@test.com",
        display_name="Admin Action Center",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def _admin_auth_context(admin: User):
    return patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    )


def _create_therapist(
    db_session: Session,
    *,
    suffix: str,
    license_number: str | None,
    calendly_user_uri: str | None,
) -> Therapist:
    user = User(
        neon_auth_sub=f"therapist-action-{suffix}-sub",
        email=f"therapist-action-{suffix}@test.com",
        display_name=f"Therapist {suffix}",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name=user.display_name,
        license_number=license_number,
        calendly_user_uri=calendly_user_uri,
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return therapist


def _create_client(db_session: Session, *, phone: str) -> Client:
    client = Client(phone_e164=phone, name=f"Client {phone[-3:]}")
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)
    return client


def _create_session(
    db_session: Session,
    *,
    client_id: int,
    therapist_id: int,
    start_time: datetime,
    duration_minutes: int = 45,
):
    session_row = TherapySession(
        client_id=client_id,
        therapist_id=therapist_id,
        start_time=start_time,
        end_time=start_time + timedelta(minutes=duration_minutes),
        duration_minutes=duration_minutes,
        status="scheduled",
        source="manual",
        currency="HKD",
    )
    db_session.add(session_row)
    db_session.commit()


def test_action_center_summary_returns_expected_counts(client, db_session: Session):
    admin = _create_admin(db_session)

    db_session.add(AccessRequest(neon_auth_sub="req-pending-1", email="p1@test.com", status="pending"))
    db_session.add(AccessRequest(neon_auth_sub="req-pending-2", email="p2@test.com", status="pending"))
    db_session.add(AccessRequest(neon_auth_sub="req-approved-1", email="a1@test.com", status="approved"))
    db_session.commit()

    therapist_1 = _create_therapist(
        db_session,
        suffix="one",
        license_number=None,
        calendly_user_uri=None,
    )
    therapist_2 = _create_therapist(
        db_session,
        suffix="two",
        license_number="PT-TWO-1",
        calendly_user_uri=None,
    )
    therapist_3 = _create_therapist(
        db_session,
        suffix="three",
        license_number="PT-THREE-1",
        calendly_user_uri="https://api.calendly.com/users/THREE",
    )

    specialty = TherapistSpecialty(name="Sports Rehab", is_active=True)
    db_session.add(specialty)
    db_session.commit()
    db_session.refresh(specialty)
    db_session.add(
        TherapistSpecialtyMap(
            therapist_id=therapist_3.id,
            specialty_id=specialty.id,
        )
    )
    db_session.commit()

    client_1 = _create_client(db_session, phone="+85290000101")
    client_2 = _create_client(db_session, phone="+85290000102")
    client_3 = _create_client(db_session, phone="+85290000103")

    now = datetime.now(timezone.utc)
    _create_session(
        db_session,
        client_id=client_1.id,
        therapist_id=therapist_1.id,
        start_time=now - timedelta(days=5),
    )
    _create_session(
        db_session,
        client_id=client_2.id,
        therapist_id=therapist_2.id,
        start_time=now + timedelta(days=1),
    )
    _create_session(
        db_session,
        client_id=client_3.id,
        therapist_id=therapist_3.id,
        start_time=now - timedelta(days=60),
    )

    plan_30 = BillingPlan(name="Plan 30", duration_minutes=30, amount_cents=75000, currency="HKD", is_active=True)
    plan_45 = BillingPlan(name="Plan 45", duration_minutes=45, amount_cents=100000, currency="HKD", is_active=True)
    db_session.add(plan_30)
    db_session.add(plan_45)
    db_session.commit()
    db_session.refresh(plan_30)
    db_session.refresh(plan_45)

    db_session.add(
        ClientPlanAssignment(
            client_id=client_1.id,
            duration_minutes=30,
            billing_plan_id=plan_30.id,
            assigned_by_user_id=admin.id,
            is_active=True,
        )
    )
    db_session.add(
        ClientPlanAssignment(
            client_id=client_2.id,
            duration_minutes=45,
            billing_plan_id=plan_45.id,
            assigned_by_user_id=admin.id,
            is_active=True,
        )
    )
    db_session.add(
        ClientFinancial(
            client_id=client_1.id,
            total_paid_cents=200000,
            total_receipted_cents=50000,
            currency="HKD",
        )
    )
    db_session.add(
        ClientFinancial(
            client_id=client_2.id,
            total_paid_cents=60000,
            total_receipted_cents=20000,
            currency="HKD",
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get("/api/v1/admin/action-center/summary", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["pending_access_requests"] == 2
    assert payload["therapists_missing_license"] == 1
    assert payload["therapists_missing_calendly"] == 2
    assert payload["therapists_missing_specialties"] == 2
    assert payload["active_clients_in_window"] == 2
    assert payload["clients_missing_plan_30"] == 1
    assert payload["clients_missing_plan_45"] == 1
    assert payload["active_clients_missing_any_plan_assignment"] == 2
    assert payload["clients_with_receipting_backlog"] == 1
    assert payload["past_sessions_missing_payment_record"] == 1
    assert payload["active_clients_missing_financial_profile"] == 0
    assert payload["lookback_days"] == 30
    assert payload["financial_alert_threshold_cents"] == 100000


def test_action_center_summary_honors_lookback_and_threshold(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(
        db_session,
        suffix="window",
        license_number="PT-WINDOW-1",
        calendly_user_uri="https://api.calendly.com/users/WINDOW",
    )

    specialty = TherapistSpecialty(name="Orthopedic", is_active=True)
    db_session.add(specialty)
    db_session.commit()
    db_session.refresh(specialty)
    db_session.add(
        TherapistSpecialtyMap(
            therapist_id=therapist.id,
            specialty_id=specialty.id,
        )
    )
    db_session.commit()

    old_client = _create_client(db_session, phone="+85290000111")
    recent_client = _create_client(db_session, phone="+85290000112")

    now = datetime.now(timezone.utc)
    _create_session(
        db_session,
        client_id=old_client.id,
        therapist_id=therapist.id,
        start_time=now - timedelta(days=10),
    )
    _create_session(
        db_session,
        client_id=recent_client.id,
        therapist_id=therapist.id,
        start_time=now - timedelta(hours=2),
    )

    plan_30 = BillingPlan(name="Window 30", duration_minutes=30, amount_cents=70000, currency="HKD", is_active=True)
    plan_45 = BillingPlan(name="Window 45", duration_minutes=45, amount_cents=90000, currency="HKD", is_active=True)
    db_session.add(plan_30)
    db_session.add(plan_45)
    db_session.commit()
    db_session.refresh(plan_30)
    db_session.refresh(plan_45)

    db_session.add(
        ClientPlanAssignment(
            client_id=recent_client.id,
            duration_minutes=30,
            billing_plan_id=plan_30.id,
            assigned_by_user_id=admin.id,
            is_active=True,
        )
    )
    db_session.add(
        ClientPlanAssignment(
            client_id=recent_client.id,
            duration_minutes=45,
            billing_plan_id=plan_45.id,
            assigned_by_user_id=admin.id,
            is_active=True,
        )
    )
    db_session.add(
        ClientFinancial(
            client_id=old_client.id,
            total_paid_cents=150000,
            total_receipted_cents=20000,
            currency="HKD",
        )
    )
    db_session.add(
        ClientFinancial(
            client_id=recent_client.id,
            total_paid_cents=50000,
            total_receipted_cents=10000,
            currency="HKD",
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get(
            "/api/v1/admin/action-center/summary?lookback_days=7&financial_alert_threshold_cents=120000",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_clients_in_window"] == 1
    assert payload["clients_missing_plan_30"] == 0
    assert payload["clients_missing_plan_45"] == 0
    assert payload["active_clients_missing_any_plan_assignment"] == 0
    assert payload["clients_with_receipting_backlog"] == 1
    assert payload["past_sessions_missing_payment_record"] == 1
    assert payload["active_clients_missing_financial_profile"] == 0
    assert payload["lookback_days"] == 7
    assert payload["financial_alert_threshold_cents"] == 120000


def test_pending_access_requests_matches_access_request_list_count(client, db_session: Session):
    admin = _create_admin(db_session)

    db_session.add(AccessRequest(neon_auth_sub="req-match-1", email="match1@test.com", status="pending"))
    db_session.add(AccessRequest(neon_auth_sub="req-match-2", email="match2@test.com", status="pending"))
    db_session.add(AccessRequest(neon_auth_sub="req-match-3", email="match3@test.com", status="approved"))
    db_session.commit()

    with _admin_auth_context(admin):
        summary_response = client.get("/api/v1/admin/action-center/summary", headers=_auth_headers())
    assert summary_response.status_code == 200
    summary_pending_count = summary_response.json()["pending_access_requests"]

    with _admin_auth_context(admin):
        list_response = client.get(
            "/api/v1/admin/access-requests?status=pending",
            headers=_auth_headers(),
        )
    assert list_response.status_code == 200
    list_pending_count = len(list_response.json())

    assert summary_pending_count == list_pending_count == 2


def test_action_center_summary_debug_ids_payload(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(
        db_session,
        suffix="debug",
        license_number=None,
        calendly_user_uri=None,
    )
    client_row = _create_client(db_session, phone="+85290000121")
    now = datetime.now(timezone.utc)
    _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=now - timedelta(days=1),
    )
    db_session.add(AccessRequest(neon_auth_sub="req-debug", email="debug@test.com", status="pending"))
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get(
            "/api/v1/admin/action-center/summary?include_debug_ids=true",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["debug_ids"] is not None
    assert payload["debug_ids"]["pending_access_request_ids"] != []
    assert payload["debug_ids"]["clients_missing_plan_30_ids"] == [client_row.id]
    assert payload["debug_ids"]["clients_missing_plan_45_ids"] == [client_row.id]
    assert payload["debug_ids"]["clients_missing_any_plan_assignment_ids"] == [client_row.id]
    assert payload["debug_ids"]["past_sessions_missing_payment_record_ids"] != []
    assert payload["debug_ids"]["active_clients_missing_financial_profile_ids"] == [client_row.id]
    # Backward-compatible keys (without _ids suffix) are always present.
    assert payload["debug_ids"]["clients_missing_plan_30"] == [client_row.id]
    assert payload["debug_ids"]["clients_missing_plan_45"] == [client_row.id]
    assert payload["debug_ids"]["active_clients_missing_any_plan_assignment"] == [client_row.id]
    assert payload["debug_ids"]["past_sessions_missing_payment_record"] != []
    assert payload["debug_ids"]["active_clients_missing_financial_profile"] == [client_row.id]


def test_action_center_summary_debug_ids_empty_lists_are_serialized(client, db_session: Session):
    admin = _create_admin(db_session)

    with _admin_auth_context(admin):
        response = client.get(
            "/api/v1/admin/action-center/summary?include_debug_ids=true",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    debug = response.json()["debug_ids"]
    assert debug is not None
    assert debug["pending_access_request_ids"] == []
    assert debug["clients_missing_plan_30_ids"] == []
    assert debug["clients_missing_plan_45_ids"] == []
    assert debug["clients_missing_any_plan_assignment_ids"] == []
    assert debug["past_sessions_missing_payment_record_ids"] == []
    assert debug["active_clients_missing_financial_profile_ids"] == []
    assert debug["clients_missing_plan_30"] == []
    assert debug["clients_missing_plan_45"] == []
    assert debug["active_clients_missing_any_plan_assignment"] == []
    assert debug["past_sessions_missing_payment_record"] == []
    assert debug["active_clients_missing_financial_profile"] == []
