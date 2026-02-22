"""Timezone serialization tests for therapist session endpoints."""

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
    preferred_timezone: str | None,
) -> tuple[User, Therapist]:
    user = User(
        neon_auth_sub=f"therapist-timezone-{suffix}-sub",
        email=f"therapist-timezone-{suffix}@test.com",
        display_name=f"Dr TZ {suffix}",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name=user.display_name,
        preferred_timezone=preferred_timezone,
        is_active=True,
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


def _create_session(
    db_session: Session,
    *,
    client_id: int,
    therapist_id: int,
    start_time: datetime,
    duration_minutes: int = 45,
) -> TherapySession:
    row = TherapySession(
        client_id=client_id,
        therapist_id=therapist_id,
        start_time=start_time,
        end_time=start_time + timedelta(minutes=duration_minutes),
        duration_minutes=duration_minutes,
        status="scheduled",
        source="manual",
        currency="HKD",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_therapist_sessions_list_uses_preferred_timezone(client, db_session: Session):
    user, therapist = _create_therapist_user(
        db_session,
        suffix="hkt",
        preferred_timezone="Asia/Hong_Kong",
    )
    client_row = Client(phone_e164="+85299900011", name="TZ Test Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    # Stored as UTC instant.
    _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=datetime(2026, 2, 22, 7, 0, tzinfo=timezone.utc),
    )

    with _therapist_auth(user):
        response = client.get("/api/v1/therapist/sessions", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    start = datetime.fromisoformat(payload[0]["start_time"])
    end = datetime.fromisoformat(payload[0]["end_time"])
    assert start.hour == 15
    assert start.utcoffset() == timedelta(hours=8)
    assert end.utcoffset() == timedelta(hours=8)


def test_therapist_summary_next_session_uses_preferred_timezone(client, db_session: Session):
    user, therapist = _create_therapist_user(
        db_session,
        suffix="summary-hkt",
        preferred_timezone="Asia/Hong_Kong",
    )
    client_row = Client(phone_e164="+85299900012", name="TZ Summary Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    start_utc = datetime.now(timezone.utc) + timedelta(hours=3)
    _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=start_utc,
    )

    with _therapist_auth(user):
        response = client.get("/api/v1/therapist/sessions/summary", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["next_session"] is not None
    start = datetime.fromisoformat(payload["next_session"]["start_time"])
    assert start.utcoffset() == timedelta(hours=8)


def test_therapist_sessions_fallback_to_default_app_timezone(client, db_session: Session):
    user, therapist = _create_therapist_user(
        db_session,
        suffix="default",
        preferred_timezone=None,
    )
    client_row = Client(phone_e164="+85299900013", name="TZ Default Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=datetime(2026, 2, 22, 7, 0, tzinfo=timezone.utc),
    )

    with _therapist_auth(user):
        response = client.get("/api/v1/therapist/sessions", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    start = datetime.fromisoformat(payload[0]["start_time"])
    # settings.invoice_timezone defaults to Asia/Hong_Kong.
    assert start.utcoffset() == timedelta(hours=8)
    assert start.hour == 15
