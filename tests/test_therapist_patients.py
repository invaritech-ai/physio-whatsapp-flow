"""Tests for therapist patient endpoints."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import Client, Session as TherapySession, Therapist, User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _create_user_with_therapist(
    db_session: Session,
    *,
    sub: str,
    email: str,
    display_name: str,
    active: bool = True,
) -> tuple[User, Therapist]:
    user = User(
        neon_auth_sub=sub,
        email=email,
        display_name=display_name,
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name=display_name,
        is_active=active,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return user, therapist


def _therapist_auth(user: User):
    return patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": user.neon_auth_sub,
            "email": user.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    )


def test_list_therapist_patients_returns_scoped_clients(client, db_session: Session):
    user_a, therapist_a = _create_user_with_therapist(
        db_session,
        sub="therapist-a-sub",
        email="therapist-a@test.com",
        display_name="Dr A",
    )
    _, therapist_b = _create_user_with_therapist(
        db_session,
        sub="therapist-b-sub",
        email="therapist-b@test.com",
        display_name="Dr B",
    )

    client_a1 = Client(phone_e164="+85281111111", name="Alice Patient", email="alice@example.com")
    client_a2 = Client(phone_e164="+85282222222", name="Bob Patient", email="bob@example.com")
    client_b1 = Client(phone_e164="+85283333333", name="Charlie Patient", email="charlie@example.com")
    db_session.add(client_a1)
    db_session.add(client_a2)
    db_session.add(client_b1)
    db_session.commit()
    db_session.refresh(client_a1)
    db_session.refresh(client_a2)
    db_session.refresh(client_b1)

    now = datetime.now(timezone.utc)
    db_session.add(
        TherapySession(
            client_id=client_a1.id,
            therapist_id=therapist_a.id,
            start_time=now - timedelta(days=1),
            end_time=now - timedelta(days=1, minutes=-45),
            duration_minutes=45,
            status="completed",
            source="manual",
            currency="HKD",
        )
    )
    db_session.add(
        TherapySession(
            client_id=client_a2.id,
            therapist_id=therapist_a.id,
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, minutes=30),
            duration_minutes=30,
            status="scheduled",
            source="manual",
            currency="HKD",
        )
    )
    db_session.add(
        TherapySession(
            client_id=client_b1.id,
            therapist_id=therapist_b.id,
            start_time=now + timedelta(days=3),
            end_time=now + timedelta(days=3, minutes=60),
            duration_minutes=60,
            status="scheduled",
            source="manual",
            currency="HKD",
        )
    )
    db_session.commit()

    with _therapist_auth(user_a):
        response = client.get("/api/v1/therapist/patients", headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    ids = {row["id"] for row in data}
    assert client_a1.id in ids
    assert client_a2.id in ids
    assert client_b1.id not in ids


def test_list_therapist_patients_supports_search(client, db_session: Session):
    user, therapist = _create_user_with_therapist(
        db_session,
        sub="therapist-search-sub",
        email="therapist-search@test.com",
        display_name="Dr Search",
    )
    c1 = Client(phone_e164="+85284444444", name="Delta One", email="delta@example.com")
    c2 = Client(phone_e164="+85285555555", name="Echo Two", email="echo@example.com")
    db_session.add(c1)
    db_session.add(c2)
    db_session.commit()
    db_session.refresh(c1)
    db_session.refresh(c2)

    now = datetime.now(timezone.utc)
    for client_row in (c1, c2):
        db_session.add(
            TherapySession(
                client_id=client_row.id,
                therapist_id=therapist.id,
                start_time=now + timedelta(days=1),
                end_time=now + timedelta(days=1, minutes=30),
                duration_minutes=30,
                status="scheduled",
                source="manual",
                currency="HKD",
            )
        )
    db_session.commit()

    with _therapist_auth(user):
        response = client.get("/api/v1/therapist/patients?q=echo", headers=_auth_headers())

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == c2.id


def test_get_therapist_patient_detail_scoped(client, db_session: Session):
    user_a, therapist_a = _create_user_with_therapist(
        db_session,
        sub="therapist-detail-a-sub",
        email="therapist-detail-a@test.com",
        display_name="Dr Detail A",
    )
    _, therapist_b = _create_user_with_therapist(
        db_session,
        sub="therapist-detail-b-sub",
        email="therapist-detail-b@test.com",
        display_name="Dr Detail B",
    )

    own_client = Client(phone_e164="+85286666666", name="Own Client")
    other_client = Client(phone_e164="+85287777777", name="Other Client")
    db_session.add(own_client)
    db_session.add(other_client)
    db_session.commit()
    db_session.refresh(own_client)
    db_session.refresh(other_client)

    now = datetime.now(timezone.utc)
    db_session.add(
        TherapySession(
            client_id=own_client.id,
            therapist_id=therapist_a.id,
            start_time=now - timedelta(days=1),
            end_time=now - timedelta(days=1, minutes=-30),
            duration_minutes=30,
            status="completed",
            source="manual",
            currency="HKD",
        )
    )
    db_session.add(
        TherapySession(
            client_id=other_client.id,
            therapist_id=therapist_b.id,
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, minutes=30),
            duration_minutes=30,
            status="scheduled",
            source="manual",
            currency="HKD",
        )
    )
    db_session.commit()

    with _therapist_auth(user_a):
        own_response = client.get(f"/api/v1/therapist/patients/{own_client.id}", headers=_auth_headers())
    assert own_response.status_code == 200
    own_data = own_response.json()
    assert own_data["id"] == own_client.id
    assert own_data["session_count"] == 1
    assert own_data["completed_session_count"] == 1

    with _therapist_auth(user_a):
        other_response = client.get(
            f"/api/v1/therapist/patients/{other_client.id}",
            headers=_auth_headers(),
        )
    assert other_response.status_code == 404


def test_list_therapist_patient_sessions_with_status_filter(client, db_session: Session):
    user, therapist = _create_user_with_therapist(
        db_session,
        sub="therapist-patient-sessions-sub",
        email="therapist-patient-sessions@test.com",
        display_name="Dr Sessions",
    )
    patient = Client(phone_e164="+85288888888", name="Filter Patient")
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)

    now = datetime.now(timezone.utc)
    db_session.add(
        TherapySession(
            client_id=patient.id,
            therapist_id=therapist.id,
            start_time=now - timedelta(days=2),
            end_time=now - timedelta(days=2, minutes=-30),
            duration_minutes=30,
            status="completed",
            source="manual",
            currency="HKD",
        )
    )
    db_session.add(
        TherapySession(
            client_id=patient.id,
            therapist_id=therapist.id,
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, minutes=45),
            duration_minutes=45,
            status="scheduled",
            source="manual",
            currency="HKD",
        )
    )
    db_session.commit()

    with _therapist_auth(user):
        response = client.get(
            f"/api/v1/therapist/patients/{patient.id}/sessions?status=completed",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "completed"


def test_non_therapist_cannot_access_therapist_patients(client, db_session: Session):
    admin = User(
        neon_auth_sub="admin-therapist-patients-sub",
        email="admin-therapist-patients@test.com",
        display_name="Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()

    with patch(
        "app.core.auth._verify_neon_token",
        return_value={"sub": admin.neon_auth_sub, "email": admin.email},
    ):
        response = client.get("/api/v1/therapist/patients", headers=_auth_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "access_denied"
