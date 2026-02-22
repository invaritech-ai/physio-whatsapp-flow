"""Tests for admin reports endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import (
    BillingPlan,
    Client,
    ClientPlanAssignment,
    Session as TherapySession,
    Therapist,
    User,
)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _create_admin(db_session: Session) -> User:
    admin = User(
        neon_auth_sub="admin-reports-sub",
        email="admin-reports@test.com",
        display_name="Admin Reports",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def _create_therapist(db_session: Session, suffix: str) -> Therapist:
    user = User(
        neon_auth_sub=f"therapist-reports-{suffix}-sub",
        email=f"therapist-reports-{suffix}@test.com",
        display_name=f"Dr Reports {suffix}",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name=user.display_name,
        license_number=f"PT-REPORT-{suffix.upper()}",
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return therapist


def _create_client(db_session: Session, phone: str, name: str) -> Client:
    client = Client(phone_e164=phone, name=name, conversation_state="IDLE")
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
    duration_minutes: int,
    status: str,
    charge_amount_cents: int | None,
) -> TherapySession:
    row = TherapySession(
        client_id=client_id,
        therapist_id=therapist_id,
        start_time=start_time,
        end_time=start_time + timedelta(minutes=duration_minutes),
        duration_minutes=duration_minutes,
        status=status,
        source="manual",
        charge_amount_cents=charge_amount_cents,
        currency="HKD",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _admin_auth_context(admin: User):
    return patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    )


def test_admin_reports_utilization_pagination_and_filter(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist_a = _create_therapist(db_session, "a")
    therapist_b = _create_therapist(db_session, "b")
    client_a = _create_client(db_session, "+85296660001", "Util A")
    client_b = _create_client(db_session, "+85296660002", "Util B")

    now = datetime.now(timezone.utc)
    period_from = now - timedelta(days=1)
    period_to = now + timedelta(days=2)

    # Therapist A
    _create_session(
        db_session,
        client_id=client_a.id,
        therapist_id=therapist_a.id,
        start_time=now + timedelta(hours=1),
        duration_minutes=45,
        status="completed",
        charge_amount_cents=100000,
    )
    _create_session(
        db_session,
        client_id=client_a.id,
        therapist_id=therapist_a.id,
        start_time=now + timedelta(hours=2),
        duration_minutes=30,
        status="scheduled",
        charge_amount_cents=None,
    )
    _create_session(
        db_session,
        client_id=client_a.id,
        therapist_id=therapist_a.id,
        start_time=now + timedelta(hours=3),
        duration_minutes=30,
        status="cancelled",
        charge_amount_cents=None,
    )
    _create_session(
        db_session,
        client_id=client_a.id,
        therapist_id=therapist_a.id,
        start_time=now + timedelta(hours=4),
        duration_minutes=45,
        status="started",
        charge_amount_cents=None,
    )
    _create_session(
        db_session,
        client_id=client_a.id,
        therapist_id=therapist_a.id,
        start_time=now + timedelta(hours=5),
        duration_minutes=30,
        status="no_show",
        charge_amount_cents=None,
    )

    # Therapist B
    _create_session(
        db_session,
        client_id=client_b.id,
        therapist_id=therapist_b.id,
        start_time=now + timedelta(hours=1),
        duration_minutes=30,
        status="completed",
        charge_amount_cents=70000,
    )

    with _admin_auth_context(admin):
        response = client.get(
            "/api/v1/admin/reports/therapist-utilization",
            params={
                "from": period_from.isoformat(),
                "to": period_to.isoformat(),
                "limit": 1,
                "offset": 0,
            },
            headers=_auth_headers(),
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["has_more"] is True
    assert len(payload["items"]) == 1

    with _admin_auth_context(admin):
        filtered = client.get(
            "/api/v1/admin/reports/therapist-utilization",
            params={
                "from": period_from.isoformat(),
                "to": period_to.isoformat(),
                "therapist_id": therapist_a.id,
            },
            headers=_auth_headers(),
        )
    assert filtered.status_code == 200
    item = filtered.json()["items"][0]
    assert item["therapist_id"] == therapist_a.id
    assert item["completed_sessions"] == 1
    assert item["scheduled_sessions"] == 1
    assert item["cancelled_sessions"] == 1
    assert item["no_show_sessions"] == 1
    assert item["utilized_minutes"] == 90


def test_admin_reports_payroll_uses_charge_and_plan_fallback(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, "pay")
    client_row = _create_client(db_session, "+85296660003", "Payroll Client")
    now = datetime.now(timezone.utc)
    period_from = now - timedelta(days=1)
    period_to = now + timedelta(days=1)

    plan = BillingPlan(
        name="Plan 45",
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
    db_session.commit()

    # Fallback to plan amount (charge is null)
    _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=now - timedelta(hours=1),
        duration_minutes=45,
        status="completed",
        charge_amount_cents=None,
    )
    # Use explicit charge amount
    _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=now,
        duration_minutes=45,
        status="completed",
        charge_amount_cents=120000,
    )
    # Should not count in payroll completed aggregates
    _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=now + timedelta(hours=1),
        duration_minutes=45,
        status="scheduled",
        charge_amount_cents=999999,
    )

    with _admin_auth_context(admin):
        response = client.get(
            "/api/v1/admin/reports/therapist-payroll",
            params={
                "from": period_from.isoformat(),
                "to": period_to.isoformat(),
                "limit": 50,
                "offset": 0,
            },
            headers=_auth_headers(),
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["therapist_id"] == therapist.id
    assert item["completed_sessions"] == 2
    assert item["payable_minutes"] == 90
    assert item["estimated_payable_cents"] == 220000
    assert item["currency"] == "HKD"


def test_admin_reports_reject_invalid_range(client, db_session: Session):
    admin = _create_admin(db_session)
    now = datetime.now(timezone.utc)

    with _admin_auth_context(admin):
        response = client.get(
            "/api/v1/admin/reports/therapist-utilization",
            params={
                "from": now.isoformat(),
                "to": (now - timedelta(hours=1)).isoformat(),
            },
            headers=_auth_headers(),
        )
    assert response.status_code == 400
