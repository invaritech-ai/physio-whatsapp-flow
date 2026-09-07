"""Tests for admin client (patient) endpoints."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import Client, ClientFinancial, MessageLog, PaymentRecord, Receipt, Session as TherapySession, Therapist, User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _create_admin(db_session: Session) -> User:
    admin = User(
        neon_auth_sub="admin-clients-sub",
        email="admin-clients@test.com",
        display_name="Admin Clients",
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


def _therapist_auth_context(therapist_user: User):
    return patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": therapist_user.neon_auth_sub,
            "email": therapist_user.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    )


def test_create_and_get_client_with_optional_fields(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="preferred")

    payload = {
        "name": "John Chan",
        "phone_e164": "+85291234567",
        "email": "john.chan@example.com",
        "date_of_birth": "1992-07-19",
        "address": "Flat 12A, Example Building, Kowloon, Hong Kong",
        "diagnosis": "Chronic plantar fasciitis",
        "preferred_therapist_id": therapist.id,
    }

    with _admin_auth_context(admin):
        create_response = client.post("/api/v1/admin/clients", json=payload, headers=_auth_headers())

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["name"] == payload["name"]
    assert created["phone_e164"] == payload["phone_e164"]
    assert created["email"] == payload["email"]
    assert created["date_of_birth"] == payload["date_of_birth"]
    assert created["address"] == payload["address"]
    assert created["diagnosis"] == payload["diagnosis"]
    assert created["preferred_therapist_id"] == therapist.id

    with _admin_auth_context(admin):
        get_response = client.get(f"/api/v1/admin/clients/{created['id']}", headers=_auth_headers())

    assert get_response.status_code == 200
    fetched = get_response.json()
    assert fetched["id"] == created["id"]
    assert fetched["email"] == payload["email"]
    assert fetched["diagnosis"] == payload["diagnosis"]

    with _admin_auth_context(admin):
        list_response = client.get("/api/v1/admin/clients", headers=_auth_headers())

    assert list_response.status_code == 200
    list_item = next(item for item in list_response.json()["items"] if item["id"] == created["id"])
    assert "diagnosis" not in list_item


def test_create_client_duplicate_phone_returns_400(client, db_session: Session):
    admin = _create_admin(db_session)
    db_session.add(Client(phone_e164="+85290000001", name="Existing"))
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.post(
            "/api/v1/admin/clients",
            json={"name": "New", "phone_e164": "+85290000001"},
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "client_phone_already_exists"


def test_list_clients_filters(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist_a = _create_therapist(db_session, suffix="a")
    therapist_b = _create_therapist(db_session, suffix="b")

    db_session.add(
        Client(
            phone_e164="+85291111111",
            name="Alice Ng",
            email="alice@example.com",
            preferred_therapist_id=therapist_a.id,
        )
    )
    db_session.add(
        Client(
            phone_e164="+85292222222",
            name="Bob Chan",
            preferred_name="Bobby",
            email="bob@example.com",
            preferred_therapist_id=therapist_b.id,
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        q_response = client.get("/api/v1/admin/clients?q=alice", headers=_auth_headers())
    assert q_response.status_code == 200
    q_payload = q_response.json()
    q_data = q_payload["items"]
    assert q_payload["total"] == 1
    assert q_payload["limit"] == 50
    assert q_payload["offset"] == 0
    assert q_payload["has_more"] is False
    assert len(q_data) == 1
    assert q_data[0]["name"] == "Alice Ng"

    with _admin_auth_context(admin):
        nick_response = client.get("/api/v1/admin/clients?q=bobby", headers=_auth_headers())
    assert nick_response.status_code == 200
    nick_data = nick_response.json()["items"]
    assert len(nick_data) == 1
    assert nick_data[0]["name"] == "Bob Chan"

    with _admin_auth_context(admin):
        phone_response = client.get(
            "/api/v1/admin/clients?phone_e164=%2B85292222222",
            headers=_auth_headers(),
        )
    assert phone_response.status_code == 200
    phone_data = phone_response.json()["items"]
    assert len(phone_data) == 1
    assert phone_data[0]["name"] == "Bob Chan"

    with _admin_auth_context(admin):
        pref_response = client.get(
            f"/api/v1/admin/clients?preferred_therapist_id={therapist_a.id}",
            headers=_auth_headers(),
        )
    assert pref_response.status_code == 200
    pref_data = pref_response.json()["items"]
    assert len(pref_data) == 1
    assert pref_data[0]["preferred_therapist_id"] == therapist_a.id


def test_patch_client_updates_and_clears_optional_fields(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="update")

    client_row = Client(
        phone_e164="+85293333333",
        name="Chris",
        email="old@example.com",
        preferred_therapist_id=therapist.id,
    )
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    with _admin_auth_context(admin):
        response = client.patch(
            f"/api/v1/admin/clients/{client_row.id}",
            json={
                "name": "Chris Updated",
                "email": "new@example.com",
                "address": "New Address",
                "diagnosis": "  Achilles tendinopathy  ",
                "preferred_therapist_id": None,
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Chris Updated"
    assert data["email"] == "new@example.com"
    assert data["address"] == "New Address"
    assert data["diagnosis"] == "Achilles tendinopathy"
    assert data["preferred_therapist_id"] is None

    with _admin_auth_context(admin):
        clear_response = client.patch(
            f"/api/v1/admin/clients/{client_row.id}",
            json={"diagnosis": "   "},
            headers=_auth_headers(),
        )

    assert clear_response.status_code == 200
    assert clear_response.json()["diagnosis"] is None


def test_list_clients_returns_pagination_metadata(client, db_session: Session):
    admin = _create_admin(db_session)
    db_session.add(Client(phone_e164="+85293330001", name="Client 1"))
    db_session.add(Client(phone_e164="+85293330002", name="Client 2"))
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get("/api/v1/admin/clients?limit=1&offset=0", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["has_more"] is True
    assert len(payload["items"]) == 1


def test_list_clients_includes_financials_summary(client, db_session: Session):
    admin = _create_admin(db_session)
    client_with_financials = Client(phone_e164="+85293331001", name="With Financials")
    client_without_financials = Client(phone_e164="+85293331002", name="Without Financials")
    db_session.add(client_with_financials)
    db_session.add(client_without_financials)
    db_session.commit()
    db_session.refresh(client_with_financials)
    db_session.refresh(client_without_financials)

    db_session.add(
        ClientFinancial(
            client_id=client_with_financials.id,
            total_paid_cents=120000,
            total_receipted_cents=90000,
            currency="HKD",
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get("/api/v1/admin/clients?limit=50&offset=0", headers=_auth_headers())

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["items"]}

    with_financials = rows[client_with_financials.id]["financials_summary"]
    assert with_financials["total_paid_cents"] == 120000
    assert with_financials["total_receipted_cents"] == 90000
    assert with_financials["available_to_receipt_cents"] == 30000
    assert with_financials["currency"] == "HKD"

    without_financials = rows[client_without_financials.id]["financials_summary"]
    assert without_financials["total_paid_cents"] is None
    assert without_financials["total_receipted_cents"] is None
    assert without_financials["available_to_receipt_cents"] is None
    assert without_financials["currency"] is None


def test_list_client_sessions_with_status_filter(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="sessions")
    client_row = Client(phone_e164="+85294444444", name="Session Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    now = datetime.now(timezone.utc)
    db_session.add(
        TherapySession(
            client_id=client_row.id,
            therapist_id=therapist.id,
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, minutes=45),
            duration_minutes=45,
            status="scheduled",
            source="manual",
            currency="HKD",
        )
    )
    db_session.add(
        TherapySession(
            client_id=client_row.id,
            therapist_id=therapist.id,
            start_time=now - timedelta(days=2),
            end_time=now - timedelta(days=2, minutes=-30),
            duration_minutes=30,
            status="completed",
            source="manual",
            currency="HKD",
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/sessions?status=completed",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "completed"


def test_list_client_sessions_flags_clinical_note_presence(client, db_session: Session):
    from app.models.session_note import SessionNote

    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="sessions-notes")
    client_row = Client(phone_e164="+85294444555", name="Notes Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    now = datetime.now(timezone.utc)
    with_note = TherapySession(
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=now - timedelta(days=1),
        end_time=now - timedelta(days=1) + timedelta(minutes=45),
        duration_minutes=45,
        status="completed",
        source="manual",
        currency="HKD",
    )
    without_note = TherapySession(
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=now - timedelta(days=3),
        end_time=now - timedelta(days=3) + timedelta(minutes=30),
        duration_minutes=30,
        status="completed",
        source="manual",
        currency="HKD",
    )
    db_session.add(with_note)
    db_session.add(without_note)
    db_session.commit()
    db_session.refresh(with_note)

    db_session.add(
        SessionNote(
            session_id=with_note.id,
            author_user_id=admin.id,
            note_text="Patient reports reduced pain. Diagnosis: Frozen Shoulder",
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/sessions",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    by_id = {row["id"]: row for row in response.json()}
    assert by_id[with_note.id]["has_clinical_note"] is True
    assert by_id[with_note.id]["clinical_note_preview"]
    assert by_id[without_note.id]["has_clinical_note"] is False
    assert by_id[without_note.id]["clinical_note_preview"] is None


def test_list_client_sessions_serializes_in_admin_preferred_timezone(client, db_session: Session):
    admin = _create_admin(db_session)
    admin.preferred_timezone = "Asia/Hong_Kong"
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    therapist = _create_therapist(db_session, suffix="sessions-tz")
    client_row = Client(phone_e164="+85294444445", name="Session TZ Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    # DB stores UTC-naive; 06:00 UTC should serialize as 14:00 +08:00.
    db_session.add(
        TherapySession(
            client_id=client_row.id,
            therapist_id=therapist.id,
            start_time=datetime(2026, 2, 23, 6, 0),
            end_time=datetime(2026, 2, 23, 6, 30),
            duration_minutes=30,
            status="scheduled",
            source="calendly",
            currency="HKD",
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/sessions",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1

    start_time = datetime.fromisoformat(data[0]["start_time"])
    end_time = datetime.fromisoformat(data[0]["end_time"])
    assert start_time.utcoffset() == timedelta(hours=8)
    assert start_time.hour == 14
    assert end_time.utcoffset() == timedelta(hours=8)
    assert end_time.hour == 14


def test_list_client_sessions_uses_confirmed_payment_total_when_session_charge_is_null(client, db_session: Session):
    admin = _create_admin(db_session)
    therapist = _create_therapist(db_session, suffix="receipt-total")
    client_row = Client(phone_e164="+85294444446", name="Receipt Total Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    session_row = TherapySession(
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=datetime(2026, 2, 23, 6, 0),
        end_time=datetime(2026, 2, 23, 6, 45),
        duration_minutes=45,
        status="completed",
        source="manual",
        charge_amount_cents=None,
        currency="HKD",
    )
    db_session.add(session_row)
    db_session.commit()
    db_session.refresh(session_row)

    db_session.add(
        PaymentRecord(
            client_id=client_row.id,
            session_id=session_row.id,
            source="session_linked",
            amount_cents=50000,
            currency="HKD",
            payment_method="cash",
            status="confirmed",
            received_by_role="therapist",
            recorded_by_user_id=admin.id,
        )
    )
    db_session.add(
        PaymentRecord(
            client_id=client_row.id,
            session_id=session_row.id,
            source="session_linked",
            amount_cents=15000,
            currency="HKD",
            payment_method="cash",
            status="confirmed",
            received_by_role="therapist",
            recorded_by_user_id=admin.id,
        )
    )
    db_session.add(
        Receipt(
            client_id=client_row.id,
            session_id=session_row.id,
            therapist_id=therapist.id,
            service_type="standard",
            amount_cents=10000,
            currency="HKD",
            description="Session partial receipt",
            payment_mode="Cash",
            diagnosis="-",
            special_notes="-",
            status="issued",
            issued_by_user_id=admin.id,
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/sessions",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["charge_amount_cents"] == 65000
    assert data[0]["currency"] == "HKD"


def test_list_client_messages_with_direction_filter(client, db_session: Session):
    admin = _create_admin(db_session)
    client_row = Client(phone_e164="+85295555555", name="Message Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    db_session.add(
        MessageLog(
            direction="inbound",
            phone_e164=client_row.phone_e164,
            body="hello",
            twilio_sid="SMMSG001",
            client_id=client_row.id,
        )
    )
    db_session.add(
        MessageLog(
            direction="outbound",
            phone_e164=client_row.phone_e164,
            body="hi there",
            twilio_sid="SMMSG002",
            client_id=client_row.id,
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/messages?direction=inbound",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["direction"] == "inbound"
    assert data["has_more"] is False


def test_list_client_messages_supports_before_id_cursor_with_ascending_page_order(client, db_session: Session):
    admin = _create_admin(db_session)
    client_row = Client(phone_e164="+85297777777", name="Message Cursor Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    inserted_ids: list[int] = []
    for idx in range(120):
        row = MessageLog(
            direction="inbound",
            phone_e164=client_row.phone_e164,
            body=f"msg-{idx + 1:03d}",
            twilio_sid=f"SMCURSOR{idx + 1:03d}",
            client_id=client_row.id,
        )
        db_session.add(row)
        db_session.flush()
        inserted_ids.append(row.id)
    db_session.commit()

    with _admin_auth_context(admin):
        page_1_response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/messages?limit=50",
            headers=_auth_headers(),
        )
    assert page_1_response.status_code == 200
    page_1 = page_1_response.json()
    page_1_ids = [item["id"] for item in page_1["items"]]
    assert page_1_ids == inserted_ids[-50:]
    assert page_1["has_more"] is True

    with _admin_auth_context(admin):
        page_2_response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/messages?limit=50&before_id={page_1_ids[0]}",
            headers=_auth_headers(),
        )
    assert page_2_response.status_code == 200
    page_2 = page_2_response.json()
    page_2_ids = [item["id"] for item in page_2["items"]]
    assert page_2_ids == inserted_ids[-100:-50]
    assert page_2["has_more"] is True

    with _admin_auth_context(admin):
        page_3_response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/messages?limit=50&before_id={page_2_ids[0]}",
            headers=_auth_headers(),
        )
    assert page_3_response.status_code == 200
    page_3 = page_3_response.json()
    page_3_ids = [item["id"] for item in page_3["items"]]
    assert page_3_ids == inserted_ids[:20]
    assert page_3["has_more"] is False


def test_get_client_financials_defaults_to_zero(client, db_session: Session):
    admin = _create_admin(db_session)
    client_row = Client(phone_e164="+85296666666", name="Financial Zero")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    with _admin_auth_context(admin):
        response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/financials",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["client_id"] == client_row.id
    assert data["total_paid_cents"] == 0
    assert data["total_receipted_cents"] == 0
    assert data["available_to_receipt_cents"] == 0


def test_get_client_financials_with_record(client, db_session: Session):
    admin = _create_admin(db_session)
    client_row = Client(phone_e164="+85297777777", name="Financial Existing")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    db_session.add(
        ClientFinancial(
            client_id=client_row.id,
            total_paid_cents=120000,
            total_receipted_cents=90000,
            currency="HKD",
        )
    )
    db_session.commit()

    with _admin_auth_context(admin):
        response = client.get(
            f"/api/v1/admin/clients/{client_row.id}/financials",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total_paid_cents"] == 120000
    assert data["total_receipted_cents"] == 90000
    assert data["available_to_receipt_cents"] == 30000


def test_non_admin_cannot_access_admin_clients(client, db_session: Session):
    therapist_user = User(
        neon_auth_sub="therapist-no-admin-sub",
        email="therapist-no-admin@test.com",
        display_name="No Admin",
        role="therapist",
        is_active=True,
    )
    db_session.add(therapist_user)
    db_session.commit()

    with _therapist_auth_context(therapist_user):
        response = client.get("/api/v1/admin/clients", headers=_auth_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "access_denied"
