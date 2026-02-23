"""Tests for admin billing queue endpoint."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import BillingPlan, Client, ClientPlanAssignment, PaymentRecord, Receipt, Session as TherapySession, Therapist, User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _create_admin(db_session: Session) -> User:
    admin = User(
        neon_auth_sub="admin-billing-queue",
        email="admin-billing-queue@test.com",
        display_name="Admin Queue",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def _create_therapist_user(db_session: Session, suffix: str) -> Therapist:
    user = User(
        neon_auth_sub=f"therapist-queue-sub-{suffix}",
        email=f"therapist-queue-{suffix}@test.com",
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
        license_number=f"PT-QUEUE-{suffix}",
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return therapist


def _create_client(db_session: Session, phone: str, default_receipt_amount_cents: int | None = None) -> Client:
    client = Client(
        phone_e164=phone, 
        name="Queue Client",
        default_receipt_amount_cents=default_receipt_amount_cents,
    )
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)
    return client


def _admin_auth_context(admin: User):
    return patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    )


def test_billing_queue_calculations_and_filtering(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist_user(db_session, "A")
    c1 = _create_client(db_session, "+85290000001", default_receipt_amount_cents=90000)
    
    plan = BillingPlan(
        name="Queue 45",
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
            client_id=c1.id,
            duration_minutes=45,
            billing_plan_id=plan.id,
            assigned_by_user_id=admin.id,
            is_active=True,
        )
    )
    db_session.commit()

    now = datetime.now(timezone.utc)
    
    # Session 1: No payment, no receipt -> needs confirmation
    s1 = TherapySession(
        client_id=c1.id,
        therapist_id=therapist.id,
        start_time=now - timedelta(days=2),
        end_time=now - timedelta(days=2, minutes=-45),
        duration_minutes=45,
        status="completed",
        source="manual",
    )
    
    # Session 2: Fully paid, fully receipted -> no confirmation
    s2 = TherapySession(
        client_id=c1.id,
        therapist_id=therapist.id,
        start_time=now - timedelta(days=1),
        end_time=now - timedelta(days=1, minutes=-45),
        duration_minutes=45,
        status="completed",
        source="manual",
    )
    
    # Session 3: Partially paid, not receipted -> needs confirmation
    s3 = TherapySession(
        client_id=c1.id,
        therapist_id=therapist.id,
        start_time=now - timedelta(hours=2),
        end_time=now - timedelta(hours=2, minutes=-45),
        duration_minutes=45,
        status="completed",
        source="manual",
    )
    
    db_session.add_all([s1, s2, s3])
    db_session.commit()
    db_session.refresh(s1)
    db_session.refresh(s2)
    db_session.refresh(s3)

    # Payments
    p2 = PaymentRecord(
        client_id=c1.id,
        session_id=s2.id,
        amount_cents=100000,
        currency="HKD",
        source="session_linked",
        payment_method="cash",
        status="confirmed",
        recorded_by_user_id=admin.id,
    )
    p3 = PaymentRecord(
        client_id=c1.id,
        session_id=s3.id,
        amount_cents=50000,
        currency="HKD",
        source="session_linked",
        payment_method="electronic",
        status="confirmed",
        recorded_by_user_id=admin.id,
    )
    db_session.add_all([p2, p3])
    db_session.commit()

    # Receipts
    r2 = Receipt(
        client_id=c1.id,
        session_id=s2.id,
        therapist_id=therapist.id,
        amount_cents=100000,
        currency="HKD",
        description="Rec 2",
        status="issued",
        issued_by_user_id=admin.id,
    )
    db_session.add(r2)
    db_session.commit()

    with _admin_auth_context(admin):
        res = client.get(
            "/api/v1/admin/billing/queue?quick_range=7d",
            headers=_auth_headers(),
        )
    assert res.status_code == 200
    data = res.json()["items"]
    assert len(data) == 3

    # The order is: needs_confirmation DESC, start_time ASC, outstanding_cents DESC
    # needs_confirmation: s1 (true, 0 paid, 0 rec -> 0 out, wait. math is paid - rec. If 0 - 0 = 0 out, then needs_confirmation = False! 
    # Ah! If outstanding_cents = max(paid_cents - receipted_cents, 0), then session 1 has 0 outstanding, so it does NOT need confirmation according to the formula.
    # Actually wait. The spec says: needs_confirmation = outstanding_cents > 0.
    # Wait, the spec also says: outstanding_cents = max(paid_cents - receipted_cents, 0).
    # If Session 1 has no payments, it has 0 outstanding cents, so needs_confirmation is false!
    # Session 2 has 100K paid, 100K receipted -> 0 outstanding -> false
    # Session 3 has 50K paid, 0 receipted -> 50K outstanding -> true

    # Check session 3
    item3 = next(i for i in data if i["session_id"] == s3.id)
    assert item3["expected_charge_cents"] == 100000
    assert item3["paid_cents"] == 50000
    assert item3["receipted_cents"] == 0
    assert item3["outstanding_cents"] == 50000
    assert item3["needs_confirmation"] is True
    assert item3["default_receipt_amount_cents"] == 90000

    # Check session 2
    item2 = next(i for i in data if i["session_id"] == s2.id)
    assert item2["paid_cents"] == 100000
    assert item2["outstanding_cents"] == 0
    assert item2["needs_confirmation"] is False

    # Check session 1
    item1 = next(i for i in data if i["session_id"] == s1.id)
    assert item1["paid_cents"] == 0
    assert item1["outstanding_cents"] == 0
    assert item1["needs_confirmation"] is False

    # Filtering by needs_confirmation=true
    with _admin_auth_context(admin):
        res_conf = client.get(
            "/api/v1/admin/billing/queue?needs_confirmation=true",
            headers=_auth_headers(),
        )
    assert res_conf.status_code == 200
    data_conf = res_conf.json()["items"]
    assert len(data_conf) == 1
    assert data_conf[0]["session_id"] == s3.id
