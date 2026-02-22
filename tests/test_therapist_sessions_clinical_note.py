"""Tests for therapist clinical-note session endpoints."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import Client, Session as TherapySession, Therapist, User


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
        neon_auth_sub=f"therapist-clinical-{suffix}-sub",
        email=f"therapist-clinical-{suffix}@test.com",
        display_name=f"Dr Clinical {suffix}",
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


def _create_session(
    db_session: Session,
    *,
    client_id: int,
    therapist_id: int,
) -> TherapySession:
    now = datetime.now(timezone.utc)
    row = TherapySession(
        client_id=client_id,
        therapist_id=therapist_id,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, minutes=45),
        duration_minutes=45,
        status="scheduled",
        source="manual",
        currency="HKD",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _therapist_auth(user: User):
    return patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": user.neon_auth_sub,
            "email": user.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    )


def test_upsert_and_get_clinical_note(client, db_session: Session):
    user, therapist = _create_therapist_user(db_session, suffix="a")
    client_row = Client(phone_e164="+85297770001", name="Clinical Client A")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
    )

    with _therapist_auth(user):
        put_response = client.put(
            f"/api/v1/therapist/sessions/{session_row.id}/clinical-note",
            json={
                "note_text": "Patient reports reduced pain after mobility drills.",
                "diagnosis": "Bilateral plantar fasciitis",
            },
            headers=_auth_headers(),
        )

    assert put_response.status_code == 200
    put_payload = put_response.json()
    assert put_payload["session_id"] == session_row.id
    assert put_payload["diagnosis"] == "Bilateral plantar fasciitis"
    assert "Diagnosis: Bilateral plantar fasciitis" in put_payload["note_text"]
    assert "\\n\\nDiagnosis: Bilateral plantar fasciitis" not in put_payload["note_text"]
    assert "\n\nDiagnosis: Bilateral plantar fasciitis" in put_payload["note_text"]

    with _therapist_auth(user):
        get_response = client.get(
            f"/api/v1/therapist/sessions/{session_row.id}/clinical-note",
            headers=_auth_headers(),
        )

    assert get_response.status_code == 200
    get_payload = get_response.json()
    assert get_payload["session_id"] == session_row.id
    assert get_payload["note_id"] == put_payload["note_id"]
    assert get_payload["diagnosis"] == "Bilateral plantar fasciitis"
    assert "\\n\\nDiagnosis: Bilateral plantar fasciitis" not in get_payload["note_text"]
    assert "\n\nDiagnosis: Bilateral plantar fasciitis" in get_payload["note_text"]


def test_upsert_existing_note_updates_same_record(client, db_session: Session):
    user, therapist = _create_therapist_user(db_session, suffix="b")
    client_row = Client(phone_e164="+85297770002", name="Clinical Client B")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
    )

    with _therapist_auth(user):
        first = client.put(
            f"/api/v1/therapist/sessions/{session_row.id}/clinical-note",
            json={"note_text": "Initial note", "diagnosis": "Diagnosis one"},
            headers=_auth_headers(),
        )
    assert first.status_code == 200
    first_payload = first.json()

    with _therapist_auth(user):
        second = client.put(
            f"/api/v1/therapist/sessions/{session_row.id}/clinical-note",
            json={"note_text": "Updated note body", "diagnosis": "Diagnosis two"},
            headers=_auth_headers(),
        )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["note_id"] == first_payload["note_id"]
    assert "Diagnosis: Diagnosis two" in second_payload["note_text"]
    assert second_payload["diagnosis"] == "Diagnosis two"


def test_upsert_without_diagnosis_returns_null_diagnosis(client, db_session: Session):
    user, therapist = _create_therapist_user(db_session, suffix="diag-null")
    client_row = Client(phone_e164="+85297770022", name="Clinical Client Null Diagnosis")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
    )

    with _therapist_auth(user):
        put_response = client.put(
            f"/api/v1/therapist/sessions/{session_row.id}/clinical-note",
            json={"note_text": "Patient tolerated load progression well."},
            headers=_auth_headers(),
        )

    assert put_response.status_code == 200
    put_payload = put_response.json()
    assert put_payload["diagnosis"] is None

    with _therapist_auth(user):
        get_response = client.get(
            f"/api/v1/therapist/sessions/{session_row.id}/clinical-note",
            headers=_auth_headers(),
        )

    assert get_response.status_code == 200
    get_payload = get_response.json()
    assert get_payload["diagnosis"] is None


def test_therapist_cannot_write_other_therapist_session(client, db_session: Session):
    user_a, therapist_a = _create_therapist_user(db_session, suffix="c")
    _, therapist_b = _create_therapist_user(db_session, suffix="d")
    client_row = Client(phone_e164="+85297770003", name="Clinical Client C")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)
    other_session = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist_b.id,
    )

    with _therapist_auth(user_a):
        response = client.put(
            f"/api/v1/therapist/sessions/{other_session.id}/clinical-note",
            json={"note_text": "Should fail"},
            headers=_auth_headers(),
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"
