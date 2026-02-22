"""Tests for therapist session status update endpoint."""

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
        neon_auth_sub=f"therapist-status-{suffix}-sub",
        email=f"therapist-status-{suffix}@test.com",
        display_name=f"Dr Status {suffix}",
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


def test_therapist_can_update_own_session_status(client, db_session: Session):
    user, therapist = _create_therapist_user(db_session, suffix="own")
    client_row = Client(phone_e164="+85298880001", name="Status Client Own")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
    )

    with _therapist_auth(user):
        response = client.patch(
            f"/api/v1/therapist/sessions/{session_row.id}/status",
            json={"status": "started"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_row.id
    assert payload["status"] == "started"
    assert payload["updated_at"] is not None

    db_session.refresh(session_row)
    assert session_row.status == "started"


def test_therapist_cannot_update_other_therapist_session_status(client, db_session: Session):
    user_a, _ = _create_therapist_user(db_session, suffix="a")
    _, therapist_b = _create_therapist_user(db_session, suffix="b")
    client_row = Client(phone_e164="+85298880002", name="Status Client Other")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)
    other_session = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist_b.id,
    )

    with _therapist_auth(user_a):
        response = client.patch(
            f"/api/v1/therapist/sessions/{other_session.id}/status",
            json={"status": "completed"},
            headers=_auth_headers(),
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_therapist_session_status_rejects_invalid_value(client, db_session: Session):
    user, therapist = _create_therapist_user(db_session, suffix="invalid")
    client_row = Client(phone_e164="+85298880003", name="Status Client Invalid")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)
    session_row = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
    )

    with _therapist_auth(user):
        response = client.patch(
            f"/api/v1/therapist/sessions/{session_row.id}/status",
            json={"status": "invalid_status"},
            headers=_auth_headers(),
        )

    assert response.status_code == 422
