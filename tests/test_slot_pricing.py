"""Tests for per-therapist slot pricing precedence and admin slot-mapping update."""

import pytest
from sqlmodel import Session, select

from app.core.auth import get_current_admin
from app.main import app
from app.models import Therapist, TherapistEventType, User
from app.services.pricing import load_therapist_slot_price_map, resolve_expected_charge


class _StubSession:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def _make_therapist_with_slot(db_session: Session, *, amount_cents: int | None) -> Therapist:
    user = User(
        neon_auth_sub="slot-price-user",
        email="slotprice@test.com",
        display_name="SlotPrice",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    therapist = Therapist(user_id=user.id, display_name="SlotPrice", is_active=True)
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    db_session.add(
        TherapistEventType(
            therapist_id=therapist.id,
            duration_minutes=60,
            scheduling_url="https://calendly.com/x/60",
            is_active=True,
            amount_cents=amount_cents,
            currency="HKD" if amount_cents is not None else None,
        )
    )
    db_session.commit()
    return therapist


def test_slot_price_wins_over_client_plan(db_session: Session):
    therapist = _make_therapist_with_slot(db_session, amount_cents=99000)
    slot_map = load_therapist_slot_price_map(db_session, therapist_ids={therapist.id})
    plan_map = {(1, 60): {"amount_cents": 130000, "currency": "HKD"}}
    session = _StubSession(
        client_id=1, therapist_id=therapist.id, duration_minutes=60,
        charge_amount_cents=None, currency="HKD",
    )
    amount, currency, assigned_plan = resolve_expected_charge(
        session, plan_map=plan_map, slot_price_map=slot_map
    )
    assert amount == 99000  # therapist slot price wins
    assert currency == "HKD"
    # The client plan is still surfaced as context.
    assert assigned_plan == plan_map[(1, 60)]


def test_falls_back_to_client_plan_when_no_slot_price(db_session: Session):
    therapist = _make_therapist_with_slot(db_session, amount_cents=None)
    slot_map = load_therapist_slot_price_map(db_session, therapist_ids={therapist.id})
    assert slot_map == {}  # no priced slots
    plan_map = {(1, 60): {"amount_cents": 130000, "currency": "HKD"}}
    session = _StubSession(
        client_id=1, therapist_id=therapist.id, duration_minutes=60,
        charge_amount_cents=None, currency="HKD",
    )
    amount, _, _ = resolve_expected_charge(session, plan_map=plan_map, slot_price_map=slot_map)
    assert amount == 130000  # client plan used


@pytest.fixture
def override_admin_auth(db_session: Session):
    admin = User(
        neon_auth_sub="auth-admin-slotprice",
        email="admin-slotprice@test.com",
        display_name="Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    app.dependency_overrides[get_current_admin] = lambda: admin
    yield admin
    app.dependency_overrides.pop(get_current_admin, None)


def test_create_therapist_with_slot_mapping_no_pat(client, db_session: Session, override_admin_auth):
    """Booking links + prices can be set at create time without a Calendly PAT."""
    from app.models import TherapistEventType

    response = client.post(
        "/api/v1/admin/therapists",
        json={
            "email": "nopat@test.com",
            "display_name": "No PAT",
            "slot_mapping": {"30": "https://cal/30", "45": "https://cal/45"},
            "slot_prices": {"30": 70000, "45": 90000},
        },
    )
    assert response.status_code == 201
    data = response.json()
    rows = db_session.exec(
        select(TherapistEventType)
        .where(TherapistEventType.therapist_id == data["id"])
        .order_by(TherapistEventType.duration_minutes)
    ).all()
    assert [(r.duration_minutes, r.scheduling_url, r.amount_cents, r.calendly_event_type_uri) for r in rows] == [
        (30, "https://cal/30", 70000, None),
        (45, "https://cal/45", 90000, None),
    ]


def test_admin_update_slot_mapping_sets_prices(client, db_session: Session, override_admin_auth, monkeypatch):
    # Create a therapist (no Calendly) to update.
    user = User(neon_auth_sub="upd-th", email="updth@test.com", display_name="Upd", role="therapist", is_active=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    therapist = Therapist(user_id=user.id, display_name="Upd", is_active=True)
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)

    monkeypatch.setattr(
        "app.api.v1.routes.admin.therapists.validate_calendly_pat",
        lambda pat: (
            True,
            {
                "valid": True,
                "user_uri": "https://api.calendly.com/users/U1",
                "name": "Upd",
                "email": "updth@test.com",
                "event_types_found": 2,
                "event_types": [
                    {"calendly_event_type_uri": "uri30", "duration_minutes": 30, "name": "30", "scheduling_url": "https://c/30"},
                    {"calendly_event_type_uri": "uri45", "duration_minutes": 45, "name": "45", "scheduling_url": "https://c/45"},
                ],
                "warnings": [],
            },
            [],
        ),
    )

    response = client.put(
        f"/api/v1/admin/therapists/{therapist.id}/slot-mapping",
        json={
            "calendly_pat": "tok",
            "slot_mapping": {"30": "https://c/30", "45": "https://c/45"},
            "slot_prices": {"30": 70000, "45": 90000},
        },
    )

    assert response.status_code == 200
    body = response.json()
    by_duration = {item["duration_minutes"]: item for item in body}
    assert by_duration[30]["amount_cents"] == 70000
    assert by_duration[45]["amount_cents"] == 90000

    rows = db_session.exec(
        select(TherapistEventType).where(TherapistEventType.therapist_id == therapist.id)
    ).all()
    assert {r.duration_minutes: r.amount_cents for r in rows} == {30: 70000, 45: 90000}
