"""Tests for admin plans/assignments/payments Phase 5 contracts."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import BillingPlan, Client, ClientFinancial, ClientPlanAssignment, Session as TherapySession, Therapist, TherapistEventType, User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _create_admin(db_session: Session) -> User:
    admin = User(
        neon_auth_sub="admin-plans-payments-sub",
        email="admin-plans-payments@test.com",
        display_name="Admin Plans Payments",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def _create_therapist_with_user(db_session: Session, *, suffix: str) -> tuple[User, Therapist]:
    user = User(
        neon_auth_sub=f"therapist-{suffix}-sub",
        email=f"therapist-{suffix}@test.com",
        display_name=f"Dr {suffix}",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name=user.display_name,
        license_number=f"PT-{suffix.upper()}",
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return user, therapist


def _create_client(db_session: Session, *, phone: str = "+85291110000") -> Client:
    client = Client(phone_e164=phone, name="Plan Client")
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)
    return client


def _create_session(
    db_session: Session,
    *,
    client_id: int,
    therapist_id: int,
    duration_minutes: int,
    amount_cents: int | None = None,
) -> TherapySession:
    now = datetime.now(timezone.utc)
    session_row = TherapySession(
        client_id=client_id,
        therapist_id=therapist_id,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, minutes=duration_minutes),
        duration_minutes=duration_minutes,
        status="scheduled",
        source="manual",
        charge_amount_cents=amount_cents,
        currency="HKD",
    )
    db_session.add(session_row)
    db_session.commit()
    db_session.refresh(session_row)
    return session_row


def _admin_auth_context(admin: User):
    return patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    )


def _therapist_auth_context(user: User):
    return patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": user.neon_auth_sub,
            "email": user.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    )


def test_get_client_plans_returns_null_for_all_supported_durations(client, db_session: Session):
    admin = _create_admin(db_session)
    client_row = _create_client(db_session)

    with _admin_auth_context(admin):
        response = client.get(f"/api/v1/admin/clients/{client_row.id}/plans", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["client_id"] == client_row.id
    assert set(payload["assignments"].keys()) == {"15", "30", "45", "60"}
    assert all(value is None for value in payload["assignments"].values())


def test_create_and_upsert_client_plans(client, db_session: Session):
    admin = _create_admin(db_session)
    client_row = _create_client(db_session, phone="+85291110001")

    with _admin_auth_context(admin):
        plan_30_response = client.post(
            "/api/v1/admin/plans",
            json={
                "name": "Regular 30",
                "duration_minutes": 30,
                "amount_cents": 75000,
                "currency": "HKD",
                "is_active": True,
            },
            headers=_auth_headers(),
        )
    assert plan_30_response.status_code == 201
    plan_30_id = plan_30_response.json()["id"]

    with _admin_auth_context(admin):
        plan_45_response = client.post(
            "/api/v1/admin/plans",
            json={
                "name": "Regular 45",
                "duration_minutes": 45,
                "amount_cents": 100000,
                "currency": "HKD",
                "is_active": True,
            },
            headers=_auth_headers(),
        )
    assert plan_45_response.status_code == 201
    plan_45_id = plan_45_response.json()["id"]

    # New durations introduced for session-plan support: 15 and 60.
    with _admin_auth_context(admin):
        plan_15_response = client.post(
            "/api/v1/admin/plans",
            json={
                "name": "Short 15",
                "duration_minutes": 15,
                "amount_cents": 40000,
                "currency": "HKD",
                "is_active": True,
            },
            headers=_auth_headers(),
        )
        plan_60_response = client.post(
            "/api/v1/admin/plans",
            json={
                "name": "Extended 60",
                "duration_minutes": 60,
                "amount_cents": 130000,
                "currency": "HKD",
                "is_active": True,
            },
            headers=_auth_headers(),
        )
    assert plan_15_response.status_code == 201
    assert plan_60_response.status_code == 201
    plan_15_id = plan_15_response.json()["id"]
    plan_60_id = plan_60_response.json()["id"]

    with _admin_auth_context(admin):
        upsert_response = client.put(
            f"/api/v1/admin/clients/{client_row.id}/plans",
            json={
                "assignments": [
                    {"duration_minutes": 15, "billing_plan_id": plan_15_id},
                    {"duration_minutes": 30, "billing_plan_id": plan_30_id},
                    {"duration_minutes": 45, "billing_plan_id": plan_45_id},
                    {"duration_minutes": 60, "billing_plan_id": plan_60_id},
                ]
            },
            headers=_auth_headers(),
        )

    assert upsert_response.status_code == 200
    payload = upsert_response.json()
    assert payload["assignments"]["15"]["plan_id"] == plan_15_id
    assert payload["assignments"]["30"]["plan_id"] == plan_30_id
    assert payload["assignments"]["45"]["plan_id"] == plan_45_id
    assert payload["assignments"]["60"]["plan_id"] == plan_60_id


def test_upsert_client_plan_rejects_duration_mismatch(client, db_session: Session):
    admin = _create_admin(db_session)
    client_row = _create_client(db_session, phone="+85291110002")
    plan_45 = BillingPlan(
        name="Regular 45",
        duration_minutes=45,
        amount_cents=100000,
        currency="HKD",
        is_active=True,
    )
    db_session.add(plan_45)
    db_session.commit()
    db_session.refresh(plan_45)

    with _admin_auth_context(admin):
        response = client.put(
            f"/api/v1/admin/clients/{client_row.id}/plans",
            json={
                "assignments": [
                    {"duration_minutes": 30, "billing_plan_id": plan_45.id},
                ]
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "plan_duration_mismatch"


def test_record_payment_returns_payment_and_financial_snapshot(client, db_session: Session):
    admin = _create_admin(db_session)
    _, therapist = _create_therapist_with_user(db_session, suffix="pay-one")
    client_row = _create_client(db_session, phone="+85291110003")
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        duration_minutes=45,
        amount_cents=100000,
    )

    with _admin_auth_context(admin):
        response = client.post(
            "/api/v1/admin/payments",
            json={
                "client_id": client_row.id,
                "session_id": session_row.id,
                "amount_cents": 50000,
                "currency": "HKD",
                "method": "electronic",
                "received_by_role": "therapist",
                "received_by_name": "Dr Pay One",
                "reference": "FPS-001",
                "notes": "First installment",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["payment"]["client_id"] == client_row.id
    assert payload["payment"]["source"] == "session_linked"
    assert payload["payment"]["session_id"] == session_row.id
    assert payload["payment"]["method"] == "electronic"
    assert payload["financials"]["total_paid_cents"] == 50000
    assert payload["financials"]["available_to_receipt_cents"] == 50000


def test_list_payments_filters_by_client_and_method(client, db_session: Session):
    admin = _create_admin(db_session)
    _, therapist = _create_therapist_with_user(db_session, suffix="pay-two")
    client_a = _create_client(db_session, phone="+85291110004")
    client_b = _create_client(db_session, phone="+85291110005")
    session_a = _create_session(db_session, client_id=client_a.id, therapist_id=therapist.id, duration_minutes=45)
    session_b = _create_session(db_session, client_id=client_b.id, therapist_id=therapist.id, duration_minutes=45)

    with _admin_auth_context(admin):
        client.post(
            "/api/v1/admin/payments",
            json={
                "client_id": client_a.id,
                "session_id": session_a.id,
                "amount_cents": 30000,
                "currency": "HKD",
                "method": "cash",
                "received_by_role": "admin",
            },
            headers=_auth_headers(),
        )
    with _admin_auth_context(admin):
        client.post(
            "/api/v1/admin/payments",
            json={
                "client_id": client_b.id,
                "session_id": session_b.id,
                "amount_cents": 20000,
                "currency": "HKD",
                "method": "electronic",
                "received_by_role": "therapist",
            },
            headers=_auth_headers(),
        )

    with _admin_auth_context(admin):
        response = client.get(
            f"/api/v1/admin/payments?client_id={client_a.id}&method=cash",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["client_id"] == client_a.id
    assert data[0]["source"] == "session_linked"
    assert data[0]["method"] == "cash"


def test_record_payment_rejects_session_linked_without_session_id(client, db_session: Session):
    admin = _create_admin(db_session)
    client_row = _create_client(db_session, phone="+85291110008")

    with _admin_auth_context(admin):
        response = client.post(
            "/api/v1/admin/payments",
            json={
                "client_id": client_row.id,
                "source": "session_linked",
                "amount_cents": 10000,
                "currency": "HKD",
                "method": "cash",
                "received_by_role": "admin",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "payment_source_requires_session_id"


def test_record_payment_rejects_admin_manual_with_session_id(client, db_session: Session):
    admin = _create_admin(db_session)
    _, therapist = _create_therapist_with_user(db_session, suffix="pay-three")
    client_row = _create_client(db_session, phone="+85291110009")
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        duration_minutes=30,
    )

    with _admin_auth_context(admin):
        response = client.post(
            "/api/v1/admin/payments",
            json={
                "client_id": client_row.id,
                "source": "admin_manual",
                "session_id": session_row.id,
                "amount_cents": 10000,
                "currency": "HKD",
                "method": "cash",
                "received_by_role": "admin",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "admin_manual_requires_null_session_id"


def test_record_admin_manual_payment_and_list_source(client, db_session: Session):
    admin = _create_admin(db_session)
    client_row = _create_client(db_session, phone="+85291110010")

    with _admin_auth_context(admin):
        create_response = client.post(
            "/api/v1/admin/payments",
            json={
                "client_id": client_row.id,
                "source": "admin_manual",
                "amount_cents": 12000,
                "currency": "HKD",
                "method": "electronic",
                "received_by_role": "admin",
                "reference": "MANUAL-001",
            },
            headers=_auth_headers(),
        )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["payment"]["source"] == "admin_manual"
    assert created["payment"]["session_id"] is None

    with _admin_auth_context(admin):
        list_response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/payments?source=admin_manual",
            headers=_auth_headers(),
        )
    assert list_response.status_code == 200
    items = list_response.json()
    assert len(items) == 1
    assert items[0]["source"] == "admin_manual"


def test_session_payloads_include_expected_charge_and_assigned_plan(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist_user, therapist = _create_therapist_with_user(db_session, suffix="pricing")
    client_row = _create_client(db_session, phone="+85291110006")
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        duration_minutes=45,
        amount_cents=12345,
    )

    plan = BillingPlan(
        name="Regular 45",
        duration_minutes=45,
        amount_cents=100000,
        currency="HKD",
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)

    assignment = ClientPlanAssignment(
        client_id=client_row.id,
        duration_minutes=45,
        billing_plan_id=plan.id,
        assigned_by_user_id=admin.id,
        is_active=True,
    )
    db_session.add(assignment)
    db_session.commit()

    with _therapist_auth_context(therapist_user):
        therapist_list_response = client.get("/api/v1/therapist/sessions", headers=_auth_headers())
    assert therapist_list_response.status_code == 200
    therapist_list = therapist_list_response.json()["items"]
    assert therapist_list[0]["expected_charge_cents"] == 100000
    assert therapist_list[0]["expected_charge_currency"] == "HKD"
    assert therapist_list[0]["assigned_plan"]["plan_id"] == plan.id

    with _therapist_auth_context(therapist_user):
        therapist_detail_response = client.get(
            f"/api/v1/therapist/sessions/{session_row.id}",
            headers=_auth_headers(),
        )
    assert therapist_detail_response.status_code == 200
    therapist_detail = therapist_detail_response.json()
    assert therapist_detail["expected_charge_cents"] == 100000
    assert therapist_detail["assigned_plan"]["plan_name"] == "Regular 45"

    with _admin_auth_context(admin):
        admin_client_sessions_response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/sessions",
            headers=_auth_headers(),
        )
    assert admin_client_sessions_response.status_code == 200
    admin_client_sessions = admin_client_sessions_response.json()
    assert admin_client_sessions[0]["expected_charge_cents"] == 100000
    assert admin_client_sessions[0]["assigned_plan"]["plan_id"] == plan.id

    with _therapist_auth_context(therapist_user):
        therapist_patient_sessions_response = client.get(
            f"/api/v1/therapist/patients/{client_row.id}/sessions",
            headers=_auth_headers(),
        )
    assert therapist_patient_sessions_response.status_code == 200
    therapist_patient_sessions = therapist_patient_sessions_response.json()
    assert therapist_patient_sessions[0]["expected_charge_cents"] == 100000
    assert therapist_patient_sessions[0]["assigned_plan"]["duration_minutes"] == 45


def test_invoice_generation_defaults_amount_from_assigned_plan_when_omitted(client, db_session: Session):
    admin = _create_admin(db_session)
    _, therapist = _create_therapist_with_user(db_session, suffix="invoice-default")
    client_row = _create_client(db_session, phone="+85291110007")
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        duration_minutes=45,
        amount_cents=None,
    )
    plan = BillingPlan(
        name="Regular 45",
        duration_minutes=45,
        amount_cents=100000,
        currency="HKD",
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    db_session.add(
        ClientPlanAssignment(
            client_id=client_row.id,
            duration_minutes=45,
            billing_plan_id=plan.id,
            assigned_by_user_id=admin.id,
            is_active=True,
        )
    )
    db_session.add(
        ClientFinancial(
            client_id=client_row.id,
            total_paid_cents=100000,
            total_receipted_cents=0,
            currency="HKD",
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.post(
            "/api/v1/admin/invoices/generate",
            json={
                "client_id": client_row.id,
                "session_id": session_row.id,
                "currency": "HKD",
                "description": "Auto amount from assigned plan",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["amount_cents"] == 100000


def test_create_plan_rejects_unsupported_duration(client, db_session: Session):
    """Durations outside SUPPORTED_PLAN_DURATIONS are rejected at plan creation."""
    admin = _create_admin(db_session)
    with _admin_auth_context(admin):
        response = client.post(
            "/api/v1/admin/plans",
            json={
                "name": "Bad duration",
                "duration_minutes": 20,
                "amount_cents": 50000,
                "currency": "HKD",
                "is_active": True,
            },
            headers=_auth_headers(),
        )
    assert response.status_code == 422
    assert "must be one of [15, 30, 45, 60]" in response.text


def test_invoice_generation_defaults_amount_from_15min_plan(client, db_session: Session):
    """A 15-minute session receipt draws its amount from the client's 15-min plan."""
    admin = _create_admin(db_session)
    _, therapist = _create_therapist_with_user(db_session, suffix="invoice-15")
    client_row = _create_client(db_session, phone="+85291110015")
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        duration_minutes=15,
        amount_cents=None,
    )
    plan = BillingPlan(
        name="Short 15",
        duration_minutes=15,
        amount_cents=40000,
        currency="HKD",
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    db_session.add(
        ClientPlanAssignment(
            client_id=client_row.id,
            duration_minutes=15,
            billing_plan_id=plan.id,
            assigned_by_user_id=admin.id,
            is_active=True,
        )
    )
    db_session.add(
        ClientFinancial(
            client_id=client_row.id,
            total_paid_cents=40000,
            total_receipted_cents=0,
            currency="HKD",
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.post(
            "/api/v1/admin/invoices/generate",
            json={
                "client_id": client_row.id,
                "session_id": session_row.id,
                "currency": "HKD",
                "description": "Auto amount from 15-min plan",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 201
    assert response.json()["amount_cents"] == 40000


def test_set_therapist_payouts_updates_event_types(client, db_session: Session):
    """Admin can set per-duration therapist compensation used by payroll."""
    admin = _create_admin(db_session)
    _, therapist = _create_therapist_with_user(db_session, suffix="payout-set")
    # Event types must exist for the durations before a payout can be set.
    for duration in (15, 60):
        db_session.add(
            TherapistEventType(
                therapist_id=therapist.id,
                duration_minutes=duration,
                scheduling_url=f"https://cal/{duration}",
                is_active=True,
            )
        )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.put(
            f"/api/v1/admin/therapists/{therapist.id}/payouts",
            json={"payouts": {"15": 20000, "60": 90000}},
            headers=_auth_headers(),
        )
    assert response.status_code == 200
    payouts = {row["duration_minutes"]: row["payout_cents"] for row in response.json()}
    assert payouts[15] == 20000
    assert payouts[60] == 90000

    # Unsupported duration is rejected.
    with _admin_auth_context(admin):
        bad = client.put(
            f"/api/v1/admin/therapists/{therapist.id}/payouts",
            json={"payouts": {"20": 10000}},
            headers=_auth_headers(),
        )
    assert bad.status_code == 400
    assert "unsupported_duration" in bad.text
