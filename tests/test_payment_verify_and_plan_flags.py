"""Tests for payment verification, plan assignment flags, and bank_transfer method."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import (
    BillingPlan,
    Client,
    ClientFinancial,
    ClientPlanAssignment,
    PaymentRecord,
    Session as TherapySession,
    SessionNote,
    Therapist,
    User,
)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _create_admin(db_session: Session, *, suffix: str = "verify") -> User:
    admin = User(
        neon_auth_sub=f"admin-{suffix}-sub",
        email=f"admin-{suffix}@test.com",
        display_name=f"Admin {suffix}",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def _create_therapist(db_session: Session, *, suffix: str) -> Therapist:
    user = User(
        neon_auth_sub=f"therapist-{suffix}-sub",
        email=f"therapist-{suffix}@test.com",
        display_name=f"Dr {suffix.title()}",
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
    return therapist


def _create_client(db_session: Session, *, phone: str, name: str = "Test Client") -> Client:
    client = Client(phone_e164=phone, name=name)
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)
    return client


def _create_completed_session(
    db_session: Session,
    *,
    client_id: int,
    therapist_id: int,
    duration_minutes: int = 45,
) -> TherapySession:
    now = datetime.now(timezone.utc)
    session_row = TherapySession(
        client_id=client_id,
        therapist_id=therapist_id,
        start_time=now - timedelta(hours=2),
        end_time=now - timedelta(hours=2) + timedelta(minutes=duration_minutes),
        duration_minutes=duration_minutes,
        status="completed",
        source="manual",
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


# ── Ask 1: Plan assignment flags on client list ──


def test_client_list_includes_plan_flags_false_by_default(client, db_session: Session):
    admin = _create_admin(db_session, suffix="plan-flags-1")
    _create_client(db_session, phone="+85290200001")

    with _admin_auth_context(admin):
        response = client.get("/api/v1/admin/clients", headers=_auth_headers())

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 1
    item = items[0]
    assert item["has_30min_plan"] is False
    assert item["has_45min_plan"] is False


def test_client_list_shows_active_plan_flags(client, db_session: Session):
    admin = _create_admin(db_session, suffix="plan-flags-2")
    client_row = _create_client(db_session, phone="+85290200002")

    plan_30 = BillingPlan(name="Reg 30", duration_minutes=30, amount_cents=75000, currency="HKD", is_active=True)
    plan_45 = BillingPlan(name="Reg 45", duration_minutes=45, amount_cents=100000, currency="HKD", is_active=True)
    db_session.add_all([plan_30, plan_45])
    db_session.commit()
    db_session.refresh(plan_30)
    db_session.refresh(plan_45)

    db_session.add(ClientPlanAssignment(
        client_id=client_row.id, duration_minutes=30, billing_plan_id=plan_30.id,
        assigned_by_user_id=admin.id, is_active=True,
    ))
    db_session.add(ClientPlanAssignment(
        client_id=client_row.id, duration_minutes=45, billing_plan_id=plan_45.id,
        assigned_by_user_id=admin.id, is_active=True,
    ))
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get("/api/v1/admin/clients", headers=_auth_headers())

    assert response.status_code == 200
    items = response.json()["items"]
    target = next(i for i in items if i["id"] == client_row.id)
    assert target["has_30min_plan"] is True
    assert target["has_45min_plan"] is True


def test_client_list_inactive_plan_not_flagged(client, db_session: Session):
    admin = _create_admin(db_session, suffix="plan-flags-3")
    client_row = _create_client(db_session, phone="+85290200003")

    plan_30 = BillingPlan(name="Reg 30", duration_minutes=30, amount_cents=75000, currency="HKD", is_active=True)
    db_session.add(plan_30)
    db_session.commit()
    db_session.refresh(plan_30)

    db_session.add(ClientPlanAssignment(
        client_id=client_row.id, duration_minutes=30, billing_plan_id=plan_30.id,
        assigned_by_user_id=admin.id, is_active=False,
    ))
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get("/api/v1/admin/clients", headers=_auth_headers())

    assert response.status_code == 200
    items = response.json()["items"]
    target = next(i for i in items if i["id"] == client_row.id)
    assert target["has_30min_plan"] is False


# ── Ask 2a: Therapist payment now creates pending status ──


def test_therapist_payment_creates_pending_status(client, db_session: Session):
    therapist = _create_therapist(db_session, suffix="pend-1")
    therapist_user = db_session.get(User, therapist.user_id)
    client_row = _create_client(db_session, phone="+85290200004")
    session_row = _create_completed_session(
        db_session, client_id=client_row.id, therapist_id=therapist.id,
    )

    with _therapist_auth_context(therapist_user):
        response = client.post(
            f"/api/v1/therapist/sessions/{session_row.id}/payment",
            json={"amount_cents": 50000, "method": "cash"},
            headers=_auth_headers(),
        )

    assert response.status_code == 201

    # Verify payment is pending in DB
    from sqlmodel import select
    payment = db_session.exec(
        select(PaymentRecord).where(PaymentRecord.session_id == session_row.id)
    ).first()
    assert payment is not None
    assert payment.status == "pending"

    # Verify no financial update happened
    financial = db_session.exec(
        select(ClientFinancial).where(ClientFinancial.client_id == client_row.id)
    ).first()
    assert financial is None


# ── Ask 2b: Payment verification endpoint ──


def test_verify_payment_confirms_and_updates_financials(client, db_session: Session):
    admin = _create_admin(db_session, suffix="verify-1")
    therapist = _create_therapist(db_session, suffix="verify-1")
    client_row = _create_client(db_session, phone="+85290200005")
    session_row = _create_completed_session(
        db_session, client_id=client_row.id, therapist_id=therapist.id,
    )

    payment = PaymentRecord(
        client_id=client_row.id,
        source="session_linked",
        session_id=session_row.id,
        amount_cents=50000,
        currency="HKD",
        payment_method="cash",
        status="pending",
        received_by_role="therapist",
        recorded_by_user_id=admin.id,
    )
    db_session.add(payment)
    db_session.commit()
    db_session.refresh(payment)

    with _admin_auth_context(admin):
        response = client.post(
            f"/api/v1/admin/payments/{payment.id}/verify",
            json={"auto_generate_receipt": False},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["payment"]["status"] == "confirmed"
    assert data["financials"]["total_paid_cents"] == 50000
    assert data["receipt"] is None


def test_verify_payment_rejects_non_pending(client, db_session: Session):
    admin = _create_admin(db_session, suffix="verify-2")
    client_row = _create_client(db_session, phone="+85290200006")

    payment = PaymentRecord(
        client_id=client_row.id,
        source="admin_manual",
        amount_cents=30000,
        currency="HKD",
        payment_method="electronic",
        status="confirmed",
        received_by_role="admin",
        recorded_by_user_id=admin.id,
    )
    db_session.add(payment)
    db_session.commit()
    db_session.refresh(payment)

    with _admin_auth_context(admin):
        response = client.post(
            f"/api/v1/admin/payments/{payment.id}/verify",
            json={},
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "payment_not_pending"


def test_verify_payment_not_found(client, db_session: Session):
    admin = _create_admin(db_session, suffix="verify-3")

    with _admin_auth_context(admin):
        response = client.post(
            "/api/v1/admin/payments/99999/verify",
            json={},
            headers=_auth_headers(),
        )

    assert response.status_code == 404


def test_verify_payment_with_auto_receipt(client, db_session: Session):
    admin = _create_admin(db_session, suffix="verify-4")
    therapist = _create_therapist(db_session, suffix="verify-4")
    client_row = _create_client(db_session, phone="+85290200007", name="Receipt Client")
    client_row.default_receipt_amount_cents = 65000
    db_session.add(client_row)
    db_session.commit()

    session_row = _create_completed_session(
        db_session, client_id=client_row.id, therapist_id=therapist.id, duration_minutes=45,
    )

    # Add clinical note with diagnosis
    therapist_user = db_session.get(User, therapist.user_id)
    note = SessionNote(
        session_id=session_row.id,
        author_user_id=therapist_user.id,
        note_text="Diagnosis: Bilateral plantar fasciitis\nTreatment: stretching exercises",
    )
    db_session.add(note)

    payment = PaymentRecord(
        client_id=client_row.id,
        source="session_linked",
        session_id=session_row.id,
        amount_cents=65000,
        currency="HKD",
        payment_method="cash",
        status="pending",
        received_by_role="therapist",
        recorded_by_user_id=admin.id,
    )
    db_session.add(payment)
    db_session.commit()
    db_session.refresh(payment)

    with _admin_auth_context(admin):
        response = client.post(
            f"/api/v1/admin/payments/{payment.id}/verify",
            json={
                "auto_generate_receipt": True,
                "supervised_exercise": True,
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["payment"]["status"] == "confirmed"
    assert data["financials"]["total_paid_cents"] == 65000
    assert data["financials"]["total_receipted_cents"] == 65000

    receipt = data["receipt"]
    assert receipt is not None
    assert receipt["client_id"] == client_row.id
    assert receipt["session_id"] == session_row.id
    assert receipt["therapist_id"] == therapist.id
    assert receipt["service_type"] == "supervised_physio"
    assert "45 minutes" in receipt["description"]
    assert receipt["amount_cents"] == 65000
    assert receipt["status"] == "issued"
    assert receipt["diagnosis"] == "Bilateral plantar fasciitis"
    assert receipt["payment_mode"] == "Cash"


def test_verify_payment_auto_receipt_uses_override_values(client, db_session: Session):
    admin = _create_admin(db_session, suffix="verify-5")
    therapist = _create_therapist(db_session, suffix="verify-5")
    client_row = _create_client(db_session, phone="+85290200008")
    session_row = _create_completed_session(
        db_session, client_id=client_row.id, therapist_id=therapist.id, duration_minutes=30,
    )

    payment = PaymentRecord(
        client_id=client_row.id,
        source="session_linked",
        session_id=session_row.id,
        amount_cents=50000,
        currency="HKD",
        payment_method="electronic",
        status="pending",
        received_by_role="therapist",
        recorded_by_user_id=admin.id,
    )
    db_session.add(payment)
    db_session.commit()
    db_session.refresh(payment)

    with _admin_auth_context(admin):
        response = client.post(
            f"/api/v1/admin/payments/{payment.id}/verify",
            json={
                "auto_generate_receipt": True,
                "amount_cents": 75000,
                "diagnosis": "Custom diagnosis override",
                "payment_mode": "Electronic",
                "supervised_exercise": False,
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    receipt = response.json()["receipt"]
    assert receipt["amount_cents"] == 75000
    assert receipt["diagnosis"] == "Custom diagnosis override"
    assert receipt["payment_mode"] == "Electronic"
    assert receipt["service_type"] == "standard"
    assert "30 minutes" in receipt["description"]


# ── Ask 3: bank_transfer payment method ──


def test_admin_record_payment_with_bank_transfer(client, db_session: Session):
    admin = _create_admin(db_session, suffix="bt-1")
    client_row = _create_client(db_session, phone="+85290200009")

    with _admin_auth_context(admin):
        response = client.post(
            "/api/v1/admin/payments",
            json={
                "client_id": client_row.id,
                "source": "admin_manual",
                "amount_cents": 50000,
                "currency": "HKD",
                "method": "bank_transfer",
                "received_by_role": "admin",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 201
    assert response.json()["payment"]["method"] == "bank_transfer"


def test_therapist_record_payment_with_bank_transfer(client, db_session: Session):
    therapist = _create_therapist(db_session, suffix="bt-2")
    therapist_user = db_session.get(User, therapist.user_id)
    client_row = _create_client(db_session, phone="+85290200010")
    session_row = _create_completed_session(
        db_session, client_id=client_row.id, therapist_id=therapist.id,
    )

    with _therapist_auth_context(therapist_user):
        response = client.post(
            f"/api/v1/therapist/sessions/{session_row.id}/payment",
            json={"amount_cents": 50000, "method": "bank_transfer"},
            headers=_auth_headers(),
        )

    assert response.status_code == 201


def test_list_payments_filter_by_bank_transfer(client, db_session: Session):
    admin = _create_admin(db_session, suffix="bt-3")
    client_row = _create_client(db_session, phone="+85290200011")

    with _admin_auth_context(admin):
        client.post(
            "/api/v1/admin/payments",
            json={
                "client_id": client_row.id,
                "source": "admin_manual",
                "amount_cents": 30000,
                "currency": "HKD",
                "method": "bank_transfer",
                "received_by_role": "admin",
            },
            headers=_auth_headers(),
        )

    with _admin_auth_context(admin):
        response = client.get(
            f"/api/v1/admin/payments?method=bank_transfer",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(item["method"] == "bank_transfer" for item in data)
