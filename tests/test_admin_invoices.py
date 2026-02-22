"""Tests for admin invoice endpoints."""

from datetime import datetime, timedelta, timezone
import re
from unittest.mock import patch

from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Client,
    ClientFinancial,
    PaymentRecord,
    Receipt,
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
        neon_auth_sub="admin-invoices-sub",
        email="admin-invoices@test.com",
        display_name="Admin Invoices",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def _create_therapist(db_session: Session, *, suffix: str) -> Therapist:
    user = User(
        neon_auth_sub=f"therapist-{suffix}-invoices-sub",
        email=f"therapist-{suffix}-invoices@test.com",
        display_name=f"Dr {suffix}",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    normalized_suffix = re.sub(r"[^A-Z0-9]+", "-", suffix.upper()).strip("-")
    therapist = Therapist(
        user_id=user.id,
        display_name=user.display_name,
        license_number=f"PT-{normalized_suffix}",
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return therapist


def _admin_auth_context(admin: User):
    return patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    )


def _create_client_and_session(
    db_session: Session,
    *,
    therapist_id: int,
    phone: str,
) -> tuple[Client, TherapySession]:
    client_row = Client(phone_e164=phone, name="Invoice Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    now = datetime.now(timezone.utc)
    session_row = TherapySession(
        client_id=client_row.id,
        therapist_id=therapist_id,
        start_time=now - timedelta(days=1),
        end_time=now - timedelta(days=1, minutes=-45),
        duration_minutes=45,
        status="completed",
        source="manual",
        charge_amount_cents=65000,
        currency="HKD",
    )
    db_session.add(session_row)
    db_session.commit()
    db_session.refresh(session_row)
    return client_row, session_row


def test_generate_invoice_success_updates_financials_and_serves_pdf(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="invoice-success")
    client_row, session_row = _create_client_and_session(
        db_session,
        therapist_id=therapist.id,
        phone="+85290100001",
    )

    db_session.add(
        ClientFinancial(
            client_id=client_row.id,
            total_paid_cents=120000,
            total_receipted_cents=20000,
            currency="HKD",
        )
    )
    db_session.commit()

    payload = {
        "client_id": client_row.id,
        "session_id": session_row.id,
        "amount_cents": 65000,
        "currency": "HKD",
        "description": "Physio session invoice",
    }
    with _admin_auth_context(admin):
        response = client.post(
            "/api/v1/admin/invoices/generate",
            json=payload,
            headers=_auth_headers(),
        )

    assert response.status_code == 201
    data = response.json()
    assert data["client_id"] == client_row.id
    assert data["session_id"] == session_row.id
    assert data["therapist_id"] == therapist.id
    assert data["service_type"] == "standard"
    assert data["trainer_name"] is None
    assert data["reference_note"] is None
    assert data["amount_cents"] == 65000
    assert data["status"] == "issued"
    assert data["pdf_url"].startswith("/generated/invoices/invoice-")

    pdf_response = client.get(data["pdf_url"])
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"].startswith("application/pdf")

    financial = db_session.exec(
        select(ClientFinancial).where(ClientFinancial.client_id == client_row.id)
    ).first()
    assert financial is not None
    assert financial.total_receipted_cents == 85000

    with _admin_auth_context(admin):
        list_response = client.get(
            f"/api/v1/admin/invoices?client_id={client_row.id}",
            headers=_auth_headers(),
        )
    assert list_response.status_code == 200
    list_data = list_response.json()
    assert len(list_data) == 1
    assert list_data[0]["id"] == data["id"]

    with _admin_auth_context(admin):
        detail_response = client.get(
            f"/api/v1/admin/invoices/{data['id']}",
            headers=_auth_headers(),
        )
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == data["id"]


def test_generate_invoice_accepts_optional_metadata_and_renders_provider_details(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="invoice-meta")
    client_row, session_row = _create_client_and_session(
        db_session,
        therapist_id=therapist.id,
        phone="+85290100008",
    )
    db_session.add(
        ClientFinancial(
            client_id=client_row.id,
            total_paid_cents=70000,
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
                "amount_cents": 65000,
                "currency": "HKD",
                "description": "Physio session invoice",
                "payment_mode": "Cash",
                "diagnosis": "Bilateral plantar fasciitis",
                "special_notes": "Bring insurer card",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 201
    data = response.json()
    assert data["therapist_id"] == therapist.id
    assert data["service_type"] == "standard"
    assert data["payment_mode"] == "Cash"
    assert data["diagnosis"] == "Bilateral plantar fasciitis"
    assert data["special_notes"] == "Bring insurer card"

    pdf_response = client.get(data["pdf_url"])
    assert pdf_response.status_code == 200
    pdf_text = pdf_response.content.decode("latin-1", errors="ignore")
    assert f"License #{therapist.license_number}" in pdf_text
    assert "Diagnosis: Bilateral plantar fasciitis" in pdf_text
    assert "Special Notes: Bring insurer card" in pdf_text


def test_generate_invoice_uses_fallbacks_for_optional_metadata(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="invoice-fallback-meta")
    client_row, session_row = _create_client_and_session(
        db_session,
        therapist_id=therapist.id,
        phone="+85290100009",
    )
    db_session.add(
        ClientFinancial(
            client_id=client_row.id,
            total_paid_cents=90000,
            total_receipted_cents=0,
            currency="HKD",
        )
    )
    db_session.add(
        PaymentRecord(
            session_id=session_row.id,
            amount_cents=65000,
            currency="HKD",
            payment_method="bank_transfer",
            status="confirmed",
            recorded_by_user_id=admin.id,
        )
    )
    db_session.add(
        SessionNote(
            session_id=session_row.id,
            author_user_id=admin.id,
            note_text="Diagnosis: Lumbar strain",
            is_read=False,
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.post(
            "/api/v1/admin/invoices/generate",
            json={
                "client_id": client_row.id,
                "session_id": session_row.id,
                "amount_cents": 65000,
                "currency": "HKD",
                "description": "Physio session invoice",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 201
    data = response.json()
    assert data["therapist_id"] == therapist.id
    assert data["service_type"] == "standard"
    assert data["payment_mode"] == "Bank Transfer"
    assert data["diagnosis"] == "Lumbar strain"
    assert data["special_notes"] == "-"


def test_generate_invoice_uses_celery_task_when_enabled(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="invoice-celery")
    client_row, session_row = _create_client_and_session(
        db_session,
        therapist_id=therapist.id,
        phone="+85290100010",
    )

    db_session.add(
        ClientFinancial(
            client_id=client_row.id,
            total_paid_cents=90000,
            total_receipted_cents=0,
            currency="HKD",
        )
    )
    db_session.commit()

    class _FakeAsyncResult:
        id = "task-invoice-1"

        def get(self, timeout: int):
            _ = timeout
            return "/generated/invoices/invoice-celery.pdf"

    with (
        _admin_auth_context(admin),
        patch.object(settings, "celery_invoice_pdf_task_enabled", True),
        patch(
            "app.tasks.invoice_documents.generate_invoice_pdf.delay",
            return_value=_FakeAsyncResult(),
        ) as mock_delay,
    ):
        response = client.post(
            "/api/v1/admin/invoices/generate",
            json={
                "client_id": client_row.id,
                "session_id": session_row.id,
                "amount_cents": 65000,
                "currency": "HKD",
                "description": "Celery invoice",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 201
    data = response.json()
    assert data["pdf_url"] == "/generated/invoices/invoice-celery.pdf"
    assert data["status"] == "issued"
    assert mock_delay.called


def test_generate_invoice_rejects_amount_exceeding_available_balance(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="invoice-guard")
    client_row, session_row = _create_client_and_session(
        db_session,
        therapist_id=therapist.id,
        phone="+85290100002",
    )

    db_session.add(
        ClientFinancial(
            client_id=client_row.id,
            total_paid_cents=50000,
            total_receipted_cents=45000,
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
                "amount_cents": 10000,
                "currency": "HKD",
                "description": "Too high",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "amount_exceeds_available_to_receipt"


def test_generate_invoice_rejects_session_client_mismatch(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="invoice-mismatch")

    client_a, _ = _create_client_and_session(
        db_session,
        therapist_id=therapist.id,
        phone="+85290100003",
    )
    client_b, session_b = _create_client_and_session(
        db_session,
        therapist_id=therapist.id,
        phone="+85290100004",
    )
    assert client_a.id != client_b.id

    db_session.add(
        ClientFinancial(
            client_id=client_a.id,
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
                "client_id": client_a.id,
                "session_id": session_b.id,
                "amount_cents": 10000,
                "currency": "HKD",
                "description": "Mismatch",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_session_for_client"


def test_list_invoices_filters_by_therapist_id(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist_a = _create_therapist(db_session, suffix="invoice-filter-a")
    therapist_b = _create_therapist(db_session, suffix="invoice-filter-b")

    client_a, session_a = _create_client_and_session(
        db_session,
        therapist_id=therapist_a.id,
        phone="+85290100005",
    )
    client_b, session_b = _create_client_and_session(
        db_session,
        therapist_id=therapist_b.id,
        phone="+85290100006",
    )

    db_session.add(
        Receipt(
            client_id=client_a.id,
            session_id=session_a.id,
            therapist_id=therapist_a.id,
            amount_cents=10000,
            currency="HKD",
            description="A",
            pdf_url="/generated/invoices/invoice-a.pdf",
            status="issued",
            issued_by_user_id=admin.id,
        )
    )
    db_session.add(
        Receipt(
            client_id=client_b.id,
            session_id=session_b.id,
            therapist_id=therapist_b.id,
            amount_cents=20000,
            currency="HKD",
            description="B",
            pdf_url="/generated/invoices/invoice-b.pdf",
            status="issued",
            issued_by_user_id=admin.id,
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get(
            f"/api/v1/admin/invoices?therapist_id={therapist_a.id}",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["session_id"] == session_a.id


def test_get_invoice_detail_returns_404_when_missing(client, db_session: Session):
    admin = _create_admin(db_session)
    with _admin_auth_context(admin):
        response = client.get("/api/v1/admin/invoices/999999", headers=_auth_headers())

    assert response.status_code == 404
    assert response.json()["detail"] == "invoice_not_found"


def test_generate_invoice_latex_falls_back_to_basic_when_engine_missing(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="invoice-latex-fallback")
    client_row, session_row = _create_client_and_session(
        db_session,
        therapist_id=therapist.id,
        phone="+85290100007",
    )
    db_session.add(
        ClientFinancial(
            client_id=client_row.id,
            total_paid_cents=90000,
            total_receipted_cents=0,
            currency="HKD",
        )
    )
    db_session.commit()

    original_renderer = settings.invoice_renderer
    original_engine = settings.invoice_latex_engine
    original_fallback = settings.invoice_latex_fallback_to_basic
    settings.invoice_renderer = "latex"
    settings.invoice_latex_engine = "missing_latex_engine"
    settings.invoice_latex_fallback_to_basic = True
    try:
        with _admin_auth_context(admin):
            response = client.post(
                "/api/v1/admin/invoices/generate",
                json={
                    "client_id": client_row.id,
                    "session_id": session_row.id,
                    "amount_cents": 10000,
                    "currency": "HKD",
                    "description": "Fallback render",
                },
                headers=_auth_headers(),
            )
    finally:
        settings.invoice_renderer = original_renderer
        settings.invoice_latex_engine = original_engine
        settings.invoice_latex_fallback_to_basic = original_fallback

    assert response.status_code == 201
    data = response.json()
    assert data["pdf_url"].startswith("/generated/invoices/invoice-")


def test_generate_invoice_sessionless_supervised_physio_payload(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="invoice-sessionless")
    client_row = Client(phone_e164="+85290100010", name="Sessionless Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    db_session.add(
        ClientFinancial(
            client_id=client_row.id,
            total_paid_cents=120000,
            total_receipted_cents=10000,
            currency="HKD",
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.post(
            "/api/v1/admin/invoices/generate",
            json={
                "client_id": client_row.id,
                "therapist_id": therapist.id,
                "service_type": "supervised_physio",
                "trainer_name": "Coach Gina",
                "reference_note": "Trainer-led supervised session; therapist passive review.",
                "amount_cents": 50000,
                "currency": "HKD",
                "description": "Supervised Physiotherapy Exercise",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 201
    data = response.json()
    assert data["session_id"] is None
    assert data["therapist_id"] == therapist.id
    assert data["service_type"] == "supervised_physio"
    assert data["trainer_name"] == "Coach Gina"
    assert "therapist passive review" in data["reference_note"].lower()
    assert data["payment_mode"] == "N/A"
    assert data["pdf_url"].startswith("/generated/invoices/invoice-")

    financial = db_session.exec(
        select(ClientFinancial).where(ClientFinancial.client_id == client_row.id)
    ).first()
    assert financial is not None
    assert financial.total_receipted_cents == 60000


def test_get_client_receipting_summary_returns_running_totals_and_pagination(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="invoice-summary")
    client_row, session_row = _create_client_and_session(
        db_session,
        therapist_id=therapist.id,
        phone="+85290100011",
    )

    financial = ClientFinancial(
        client_id=client_row.id,
        total_paid_cents=200000,
        total_receipted_cents=90000,
        currency="HKD",
    )
    db_session.add(financial)
    db_session.commit()

    now = datetime.now(timezone.utc)
    db_session.add(
        Receipt(
            client_id=client_row.id,
            session_id=session_row.id,
            therapist_id=therapist.id,
            service_type="standard",
            amount_cents=30000,
            currency="HKD",
            description="Receipt 1",
            status="issued",
            issued_by_user_id=admin.id,
            created_at=now - timedelta(days=2),
        )
    )
    db_session.add(
        Receipt(
            client_id=client_row.id,
            session_id=None,
            therapist_id=therapist.id,
            service_type="supervised_physio",
            trainer_name="Coach Gina",
            amount_cents=30000,
            currency="HKD",
            description="Receipt 2",
            status="issued",
            issued_by_user_id=admin.id,
            created_at=now - timedelta(days=1),
        )
    )
    db_session.add(
        Receipt(
            client_id=client_row.id,
            session_id=None,
            therapist_id=therapist.id,
            service_type="other",
            amount_cents=30000,
            currency="HKD",
            description="Receipt 3",
            status="issued",
            issued_by_user_id=admin.id,
            created_at=now,
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/receipting/summary?limit=2&offset=0",
            headers=_auth_headers(),
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["client_id"] == client_row.id
    assert payload["currency"] == "HKD"
    assert payload["total_paid_cents"] == 200000
    assert payload["total_receipted_cents"] == 90000
    assert payload["claimable_balance_cents"] == 110000
    assert payload["limit"] == 2
    assert payload["offset"] == 0
    assert payload["has_more"] is True
    assert len(payload["receipts"]) == 2
    assert payload["receipts"][0]["service_type"] == "other"
    assert payload["receipts"][1]["service_type"] == "supervised_physio"

    with _admin_auth_context(admin):
        page_2 = client.get(
            f"/api/v1/admin/clients/{client_row.id}/receipting/summary?limit=2&offset=2",
            headers=_auth_headers(),
        )
    assert page_2.status_code == 200
    page_2_payload = page_2.json()
    assert page_2_payload["has_more"] is False
    assert len(page_2_payload["receipts"]) == 1
