"""Tests for admin sessions management endpoints."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session, select

from app.models import (
    BillingPlan,
    Client,
    ClientPlanAssignment,
    Session as TherapySession,
    SessionNote,
    Therapist,
    User,
)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _create_admin(db_session: Session) -> User:
    admin = User(
        neon_auth_sub="admin-sessions-sub",
        email="admin-sessions@test.com",
        display_name="Admin Sessions",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def _create_therapist(db_session: Session, *, suffix: str) -> Therapist:
    user = User(
        neon_auth_sub=f"therapist-sessions-{suffix}-sub",
        email=f"therapist-sessions-{suffix}@test.com",
        display_name=f"Dr Sessions {suffix}",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name=user.display_name,
        license_number=f"PT-SES-{suffix.upper()}",
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return therapist


def _create_client(db_session: Session, *, phone: str, name: str) -> Client:
    client = Client(phone_e164=phone, name=name)
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
    source: str = "manual",
) -> TherapySession:
    row = TherapySession(
        client_id=client_id,
        therapist_id=therapist_id,
        start_time=start_time,
        end_time=start_time + timedelta(minutes=duration_minutes),
        duration_minutes=duration_minutes,
        status=status,
        source=source,
        charge_amount_cents=None,
        currency="HKD",
        calendly_event_uri=f"https://api.calendly.com/scheduled_events/{client_id}-{therapist_id}-{int(start_time.timestamp())}",
        calendly_invitee_uri=f"https://api.calendly.com/invitees/{client_id}-{therapist_id}-{int(start_time.timestamp())}",
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


def test_list_admin_sessions_returns_paginated_response(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist_a = _create_therapist(db_session, suffix="a")
    therapist_b = _create_therapist(db_session, suffix="b")
    client_a = _create_client(db_session, phone="+85295550001", name="Alice Session")
    client_b = _create_client(db_session, phone="+85295550002", name="Bob Session")
    now = datetime.now(timezone.utc)

    _create_session(
        db_session,
        client_id=client_a.id,
        therapist_id=therapist_a.id,
        start_time=now + timedelta(days=1),
        duration_minutes=45,
        status="scheduled",
    )
    _create_session(
        db_session,
        client_id=client_b.id,
        therapist_id=therapist_b.id,
        start_time=now - timedelta(days=2),
        duration_minutes=30,
        status="completed",
    )

    with _admin_auth_context(admin):
        response = client.get("/api/v1/admin/sessions?limit=20&offset=0", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["limit"] == 20
    assert payload["offset"] == 0
    assert payload["has_more"] is False
    assert len(payload["items"]) == 2
    assert payload["items"][0]["id"] is not None
    assert payload["items"][0]["client_id"] is not None
    assert payload["items"][0]["therapist_id"] is not None

    with _admin_auth_context(admin):
        filtered = client.get(
            f"/api/v1/admin/sessions?status=completed&therapist_id={therapist_b.id}&client_id={client_b.id}",
            headers=_auth_headers(),
        )
    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert filtered_payload["total"] == 1
    assert filtered_payload["items"][0]["status"] == "completed"


def test_get_admin_session_detail_includes_assigned_plan(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="detail")
    client_row = _create_client(db_session, phone="+85295550003", name="Detail Client")
    now = datetime.now(timezone.utc)
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=now,
        duration_minutes=45,
        status="scheduled",
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
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get(f"/api/v1/admin/sessions/{session_row.id}", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == session_row.id
    assert payload["client_name"] == "Detail Client"
    assert payload["therapist_name"] is not None
    assert payload["expected_charge_cents"] == 100000
    assert payload["assigned_plan"]["plan_id"] == plan.id
    assert payload["calendly_event_uri"] is not None


def test_update_admin_session_status(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="status")
    client_row = _create_client(db_session, phone="+85295550004", name="Status Client")
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=datetime.now(timezone.utc),
        duration_minutes=30,
        status="scheduled",
    )

    with _admin_auth_context(admin):
        response = client.put(
            f"/api/v1/admin/sessions/{session_row.id}",
            json={"status": "completed"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_update_admin_session_reassigns_billing_plan(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="plan")
    client_row = _create_client(db_session, phone="+85295550005", name="Plan Client")
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=datetime.now(timezone.utc),
        duration_minutes=45,
        status="scheduled",
    )
    plan_a = BillingPlan(name="Plan A 45", duration_minutes=45, amount_cents=90000, currency="HKD", is_active=True)
    plan_b = BillingPlan(name="Plan B 45", duration_minutes=45, amount_cents=110000, currency="HKD", is_active=True)
    db_session.add(plan_a)
    db_session.add(plan_b)
    db_session.commit()
    db_session.refresh(plan_a)
    db_session.refresh(plan_b)
    db_session.add(
        ClientPlanAssignment(
            client_id=client_row.id,
            duration_minutes=45,
            billing_plan_id=plan_a.id,
            assigned_by_user_id=admin.id,
            is_active=True,
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.put(
            f"/api/v1/admin/sessions/{session_row.id}",
            json={"billing_plan_id": plan_b.id, "plan_notes": "Admin reassigned"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assigned_plan"]["plan_id"] == plan_b.id
    assert payload["expected_charge_cents"] == 110000

    assignment = db_session.exec(
        select(ClientPlanAssignment).where(
            ClientPlanAssignment.client_id == client_row.id,
            ClientPlanAssignment.duration_minutes == 45,
        )
    ).first()
    assert assignment is not None
    assert assignment.billing_plan_id == plan_b.id
    assert assignment.notes == "Admin reassigned"


def test_update_admin_session_rejects_duration_mismatch(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="mismatch")
    client_row = _create_client(db_session, phone="+85295550006", name="Mismatch Client")
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=datetime.now(timezone.utc),
        duration_minutes=30,
        status="scheduled",
    )
    plan_45 = BillingPlan(name="Plan 45", duration_minutes=45, amount_cents=100000, currency="HKD", is_active=True)
    db_session.add(plan_45)
    db_session.commit()
    db_session.refresh(plan_45)

    with _admin_auth_context(admin):
        response = client.put(
            f"/api/v1/admin/sessions/{session_row.id}",
            json={"billing_plan_id": plan_45.id},
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "plan_duration_mismatch"


def test_get_admin_session_clinical_note(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="clinical")
    client_row = _create_client(db_session, phone="+85295550007", name="Clinical Admin View")
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=datetime.now(timezone.utc),
        duration_minutes=45,
        status="completed",
    )

    therapist_user = db_session.get(User, therapist.user_id)
    assert therapist_user is not None
    note = SessionNote(
        session_id=session_row.id,
        author_user_id=therapist_user.id,
        note_text="Follow-up completed. Diagnosis: Bilateral plantar fasciitis",
    )
    db_session.add(note)
    db_session.commit()
    db_session.refresh(note)

    with _admin_auth_context(admin):
        response = client.get(
            f"/api/v1/admin/sessions/{session_row.id}/clinical-note",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_row.id
    assert payload["note_id"] == note.id
    assert payload["diagnosis"] == "Bilateral plantar fasciitis"
