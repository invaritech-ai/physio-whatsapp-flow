"""Pagination behavior tests for therapist session list endpoint."""

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
        neon_auth_sub=f"therapist-pagination-{suffix}-sub",
        email=f"therapist-pagination-{suffix}@test.com",
        display_name=f"Dr Pagination {suffix}",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name=user.display_name,
        preferred_timezone="Asia/Hong_Kong",
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


def test_therapist_sessions_list_paginates_with_metadata(client, db_session: Session):
    user, therapist = _create_therapist_user(db_session, suffix="metadata")
    client_row = Client(phone_e164="+85298880001", name="Pagination Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    base = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)
    session_a = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=base,
    )
    session_b = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=base + timedelta(hours=1),
    )
    session_c = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=base + timedelta(hours=2),
    )

    with _therapist_auth(user):
        response = client.get(
            "/api/v1/therapist/sessions?limit=2&offset=1",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert payload["has_more"] is False
    assert [item["id"] for item in payload["items"]] == [session_b.id, session_c.id]
    assert payload["items"][0]["id"] != session_a.id


def test_therapist_sessions_total_is_computed_before_pagination(client, db_session: Session):
    user, therapist = _create_therapist_user(db_session, suffix="scope")
    client_row = Client(phone_e164="+85298880002", name="Scope Client")
    db_session.add(client_row)
    db_session.commit()
    db_session.refresh(client_row)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=now - timedelta(days=3),
    )
    _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=now - timedelta(days=2),
    )
    # Past sessions are ordered most-recent-first, so this is the first page item.
    most_recent_past = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=now - timedelta(days=1),
    )
    _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=now + timedelta(days=1),
    )
    second_upcoming = _create_session(
        db_session,
        client_id=client_row.id,
        therapist_id=therapist.id,
        start_time=now + timedelta(days=2),
    )

    with _therapist_auth(user):
        past_response = client.get(
            "/api/v1/therapist/sessions?scope=past&limit=1&offset=0",
            headers=_auth_headers(),
        )
        upcoming_response = client.get(
            "/api/v1/therapist/sessions?scope=upcoming&limit=1&offset=1",
            headers=_auth_headers(),
        )

    assert past_response.status_code == 200
    past_payload = past_response.json()
    assert past_payload["total"] == 3
    assert len(past_payload["items"]) == 1
    assert past_payload["has_more"] is True
    assert past_payload["items"][0]["id"] == most_recent_past.id

    assert upcoming_response.status_code == 200
    upcoming_payload = upcoming_response.json()
    assert upcoming_payload["total"] == 2
    assert len(upcoming_payload["items"]) == 1
    assert upcoming_payload["has_more"] is False
    assert upcoming_payload["items"][0]["id"] == second_upcoming.id


def test_therapist_sessions_limit_max_is_enforced(client, db_session: Session):
    user, _ = _create_therapist_user(db_session, suffix="limit")

    # Endpoint caps limit at 500 (ge=1, le=500); anything above is rejected.
    with _therapist_auth(user):
        response = client.get(
            "/api/v1/therapist/sessions?limit=501",
            headers=_auth_headers(),
        )

    assert response.status_code == 422
