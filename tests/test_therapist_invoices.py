"""Tests for therapist invoice endpoints."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import Client, Receipt, Session as TherapySession, Therapist, User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _create_therapist_user(
    db_session: Session,
    *,
    suffix: str,
) -> tuple[User, Therapist]:
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
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return user, therapist


def _create_admin(db_session: Session) -> User:
    admin = User(
        neon_auth_sub="admin-therapist-invoices-sub",
        email="admin-therapist-invoices@test.com",
        display_name="Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def _auth_context(user: User):
    return patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": user.neon_auth_sub,
            "email": user.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    )


def _create_client_session_and_receipt(
    db_session: Session,
    *,
    therapist_id: int,
    issued_by_user_id: int,
    phone: str,
    amount_cents: int,
    status: str = "issued",
) -> tuple[Client, TherapySession, Receipt]:
    client_row = Client(phone_e164=phone, name=f"Client {phone[-2:]}")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    now = datetime.now(timezone.utc)
    session_row = TherapySession(
        client_id=client_row.id,
        therapist_id=therapist_id,
        start_time=now - timedelta(days=1),
        end_time=now - timedelta(days=1, minutes=-30),
        duration_minutes=30,
        status="completed",
        source="manual",
        currency="HKD",
    )
    db_session.add(session_row)
    db_session.commit()
    db_session.refresh(session_row)

    receipt = Receipt(
        client_id=client_row.id,
        session_id=session_row.id,
        amount_cents=amount_cents,
        currency="HKD",
        description="Therapist invoice",
        pdf_url=f"/generated/invoices/invoice-{therapist_id}-{client_row.id}.pdf",
        status=status,
        issued_by_user_id=issued_by_user_id,
    )
    db_session.add(receipt)
    db_session.commit()
    db_session.refresh(receipt)
    return client_row, session_row, receipt


def test_list_therapist_invoices_returns_scoped_results(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist_user_a, therapist_a = _create_therapist_user(db_session, suffix="invoices-a")
    _, therapist_b = _create_therapist_user(db_session, suffix="invoices-b")

    _, _, own_receipt = _create_client_session_and_receipt(
        db_session,
        therapist_id=therapist_a.id,
        issued_by_user_id=admin.id,
        phone="+85290200001",
        amount_cents=30000,
    )
    _create_client_session_and_receipt(
        db_session,
        therapist_id=therapist_b.id,
        issued_by_user_id=admin.id,
        phone="+85290200002",
        amount_cents=20000,
    )

    with _auth_context(therapist_user_a):
        response = client.get("/api/v1/therapist/invoices", headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == own_receipt.id
    assert data[0]["client_phone_e164"] == "+85290200001"
    assert data[0]["pdf_url"].startswith("/generated/invoices/")


def test_get_therapist_invoice_detail_scoped(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist_user_a, therapist_a = _create_therapist_user(db_session, suffix="detail-a")
    _, therapist_b = _create_therapist_user(db_session, suffix="detail-b")

    _, _, own_receipt = _create_client_session_and_receipt(
        db_session,
        therapist_id=therapist_a.id,
        issued_by_user_id=admin.id,
        phone="+85290200003",
        amount_cents=35000,
    )
    _, _, other_receipt = _create_client_session_and_receipt(
        db_session,
        therapist_id=therapist_b.id,
        issued_by_user_id=admin.id,
        phone="+85290200004",
        amount_cents=25000,
    )

    with _auth_context(therapist_user_a):
        own_response = client.get(
            f"/api/v1/therapist/invoices/{own_receipt.id}",
            headers=_auth_headers(),
        )
    assert own_response.status_code == 200
    own_data = own_response.json()
    assert own_data["id"] == own_receipt.id
    assert own_data["client_phone_e164"] == "+85290200003"

    with _auth_context(therapist_user_a):
        other_response = client.get(
            f"/api/v1/therapist/invoices/{other_receipt.id}",
            headers=_auth_headers(),
        )
    assert other_response.status_code == 404
    assert other_response.json()["detail"] == "invoice_not_found"


def test_list_therapist_invoices_supports_status_filter(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist_user, therapist = _create_therapist_user(db_session, suffix="status")

    _create_client_session_and_receipt(
        db_session,
        therapist_id=therapist.id,
        issued_by_user_id=admin.id,
        phone="+85290200005",
        amount_cents=12000,
        status="issued",
    )
    _create_client_session_and_receipt(
        db_session,
        therapist_id=therapist.id,
        issued_by_user_id=admin.id,
        phone="+85290200006",
        amount_cents=8000,
        status="voided",
    )

    with _auth_context(therapist_user):
        response = client.get(
            "/api/v1/therapist/invoices?status=issued",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "issued"


def test_non_therapist_cannot_access_therapist_invoices(client, db_session: Session):
    admin = _create_admin(db_session)

    with _auth_context(admin):
        response = client.get("/api/v1/therapist/invoices", headers=_auth_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "access_denied"
