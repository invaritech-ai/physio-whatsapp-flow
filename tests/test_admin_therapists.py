"""Tests for admin therapist endpoints."""

import pytest
from sqlmodel import Session, select

from app.core.auth import get_current_admin
from app.main import app
from app.models import Therapist, TherapistSpecialty, TherapistSpecialtyMap, User


@pytest.fixture(autouse=True)
def override_admin_auth(db_session: Session):
    """Bypass JWT and inject an admin user for admin therapist endpoint tests."""
    admin = User(
        neon_auth_sub="auth-admin-test",
        email="admin@test.com",
        display_name="Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    app.dependency_overrides[get_current_admin] = lambda: admin
    yield
    app.dependency_overrides.pop(get_current_admin, None)


class TestCreateTherapist:
    """Tests for POST /admin/therapists"""

    def test_create_therapist_success(self, client, db_session: Session):
        """Successfully create a new therapist with User."""
        response = client.post(
            "/api/v1/admin/therapists",
            json={
                "neon_auth_sub": "auth-123",
                "email": "dr.smith@test.com",
                "display_name": "Dr. Smith",
                "calendly_user_uri": "https://calendly.com/dr-smith",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["display_name"] == "Dr. Smith"
        assert data["license_number"] is None
        assert data["calendly_user_uri"] == "https://calendly.com/dr-smith"
        assert data["is_active"] is True
        assert data["specialties"] == []
        assert "id" in data
        assert "user_id" in data

        # Verify User was created
        user = db_session.get(User, data["user_id"])
        assert user is not None
        assert user.email == "dr.smith@test.com"
        assert user.role == "therapist"

        # Verify Therapist was created
        therapist = db_session.get(Therapist, data["id"])
        assert therapist is not None
        assert therapist.user_id == user.id

    def test_create_therapist_without_neon_sub_uses_pending_sentinel(self, client, db_session: Session):
        """Admin-provisioned therapist (no neon_auth_sub) gets a pending: sentinel + is_female."""
        response = client.post(
            "/api/v1/admin/therapists",
            json={
                "email": "pending@test.com",
                "display_name": "Dr Pending",
                "license_number": "PT900900",
                "is_female": True,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["is_female"] is True

        user = db_session.get(User, data["user_id"])
        assert user.neon_auth_sub == "pending:pending@test.com"

    def test_create_therapist_without_calendly(self, client, db_session: Session):
        """Create therapist without Calendly link (optional)."""
        response = client.post(
            "/api/v1/admin/therapists",
            json={
                "neon_auth_sub": "auth-456",
                "email": "dr.jones@test.com",
                "display_name": "Dr. Jones",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["license_number"] is None
        assert data["calendly_user_uri"] is None

    def test_create_therapist_with_license_number_normalizes(self, client, db_session: Session):
        response = client.post(
            "/api/v1/admin/therapists",
            json={
                "neon_auth_sub": "auth-license-normalized",
                "email": "dr.license@test.com",
                "display_name": "Dr. License",
                "license_number": "  pt-203315  ",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["license_number"] == "PT-203315"

    def test_create_duplicate_email(self, client, db_session: Session):
        """Duplicate email should fail."""
        # Create first therapist
        user = User(
            neon_auth_sub="auth-1",
            email="dr.test@test.com",
            display_name="Dr. Test",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Try to create with same email
        response = client.post(
            "/api/v1/admin/therapists",
            json={
                "neon_auth_sub": "auth-2",
                "email": "dr.test@test.com",
                "display_name": "Dr. New",
            },
        )

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    def test_create_duplicate_license_number_returns_400(self, client, db_session: Session):
        existing_user = User(
            neon_auth_sub="auth-therapist-existing-license",
            email="existing-license@test.com",
            display_name="Dr Existing License",
            role="therapist",
            is_active=True,
        )
        db_session.add(existing_user)
        db_session.commit()
        db_session.refresh(existing_user)

        existing_therapist = Therapist(
            user_id=existing_user.id,
            display_name="Dr Existing License",
            license_number="PT-203315",
            is_active=True,
        )
        db_session.add(existing_therapist)
        db_session.commit()

        response = client.post(
            "/api/v1/admin/therapists",
            json={
                "neon_auth_sub": "auth-duplicate-license",
                "email": "duplicate-license@test.com",
                "display_name": "Dr Duplicate License",
                "license_number": "pt-203315",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "license_number_already_exists"


class TestListTherapists:
    """Tests for GET /admin/therapists"""

    def test_list_therapists(self, client, db_session: Session):
        """List all therapists."""
        # Create test therapists
        for i in range(3):
            user = User(
                neon_auth_sub=f"auth-{i}",
                email=f"dr{i}@test.com",
                display_name=f"Dr. Test {i}",
                role="therapist",
                is_active=True,
            )
            db_session.add(user)
        db_session.commit()
        db_session.flush()

        users = db_session.exec(select(User).where(User.role == "therapist")).all()
        for user in users:
            therapist = Therapist(
                user_id=user.id, display_name=user.display_name, is_active=True
            )
            db_session.add(therapist)
        db_session.commit()

        response = client.get("/api/v1/admin/therapists")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        # Should have email and specialty_count
        assert all("email" in t for t in data)
        assert all("specialty_count" in t for t in data)
        assert all("license_number" in t for t in data)

    def test_list_empty_therapists(self, client, db_session: Session):
        """List when no therapists exist."""
        response = client.get("/api/v1/admin/therapists")

        assert response.status_code == 200
        assert response.json() == []


class TestGetTherapist:
    """Tests for GET /admin/therapists/{id}"""

    def test_get_therapist_success(self, client, db_session: Session):
        """Get therapist detail with specialties."""
        # Create therapist
        user = User(
            neon_auth_sub="auth-1",
            email="dr@test.com",
            display_name="Dr. Test",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.flush()

        therapist = Therapist(
            user_id=user.id,
            display_name="Dr. Test",
            calendly_user_uri="https://calendly.com/test",
            is_active=True,
        )
        db_session.add(therapist)
        db_session.commit()
        db_session.refresh(therapist)

        response = client.get(f"/api/v1/admin/therapists/{therapist.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == therapist.id
        assert data["display_name"] == "Dr. Test"
        assert data["license_number"] is None
        assert data["calendly_user_uri"] == "https://calendly.com/test"
        assert data["specialties"] == []

    def test_get_nonexistent_therapist(self, client, db_session: Session):
        """Get nonexistent therapist should return 404."""
        response = client.get("/api/v1/admin/therapists/99999")

        assert response.status_code == 404


class TestUpdateTherapist:
    """Tests for PATCH /admin/therapists/{id}"""

    def test_update_therapist_display_name(self, client, db_session: Session):
        """Update therapist display name."""
        # Create therapist
        user = User(
            neon_auth_sub="auth-1",
            email="dr@test.com",
            display_name="Dr. Old",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.flush()

        therapist = Therapist(
            user_id=user.id, display_name="Dr. Old", is_active=True
        )
        db_session.add(therapist)
        db_session.commit()
        db_session.refresh(therapist)

        response = client.patch(
            f"/api/v1/admin/therapists/{therapist.id}",
            json={"display_name": "Dr. New"},
        )

        assert response.status_code == 200
        assert response.json()["display_name"] == "Dr. New"

        # Verify in database
        db_session.refresh(therapist)
        assert therapist.display_name == "Dr. New"

    def test_update_therapist_calendly_user_uri(self, client, db_session: Session):
        """Update therapist Calendly link."""
        # Create therapist
        user = User(
            neon_auth_sub="auth-1",
            email="dr@test.com",
            display_name="Dr. Test",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.flush()

        therapist = Therapist(user_id=user.id, display_name="Dr. Test", is_active=True)
        db_session.add(therapist)
        db_session.commit()
        db_session.refresh(therapist)

        response = client.patch(
            f"/api/v1/admin/therapists/{therapist.id}",
            json={"calendly_user_uri": "https://calendly.com/updated"},
        )

        assert response.status_code == 200
        assert response.json()["calendly_user_uri"] == "https://calendly.com/updated"

    def test_update_therapist_license_number(self, client, db_session: Session):
        user = User(
            neon_auth_sub="auth-license-update",
            email="dr-license-update@test.com",
            display_name="Dr. License Update",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        therapist = Therapist(user_id=user.id, display_name="Dr. License Update", is_active=True)
        db_session.add(therapist)
        db_session.commit()
        db_session.refresh(therapist)

        response = client.patch(
            f"/api/v1/admin/therapists/{therapist.id}",
            json={"license_number": "pt 777"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["license_number"] == "PT 777"

    def test_update_therapist_duplicate_license_number_returns_400(self, client, db_session: Session):
        user_a = User(
            neon_auth_sub="auth-license-a",
            email="dr-license-a@test.com",
            display_name="Dr. License A",
            role="therapist",
            is_active=True,
        )
        user_b = User(
            neon_auth_sub="auth-license-b",
            email="dr-license-b@test.com",
            display_name="Dr. License B",
            role="therapist",
            is_active=True,
        )
        db_session.add(user_a)
        db_session.add(user_b)
        db_session.commit()
        db_session.refresh(user_a)
        db_session.refresh(user_b)

        therapist_a = Therapist(
            user_id=user_a.id,
            display_name="Dr. License A",
            license_number="PT-ABC-1",
            is_active=True,
        )
        therapist_b = Therapist(
            user_id=user_b.id,
            display_name="Dr. License B",
            is_active=True,
        )
        db_session.add(therapist_a)
        db_session.add(therapist_b)
        db_session.commit()
        db_session.refresh(therapist_b)

        response = client.patch(
            f"/api/v1/admin/therapists/{therapist_b.id}",
            json={"license_number": "pt-abc-1"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "license_number_already_exists"


class TestDeleteTherapist:
    """Tests for DELETE /admin/therapists/{id}"""

    def test_delete_therapist_soft_delete(self, client, db_session: Session):
        """Delete should soft-delete (set is_active=false)."""
        # Create therapist
        user = User(
            neon_auth_sub="auth-1",
            email="dr@test.com",
            display_name="Dr. Test",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.flush()

        therapist = Therapist(user_id=user.id, display_name="Dr. Test", is_active=True)
        db_session.add(therapist)
        db_session.commit()
        db_session.refresh(therapist)
        therapist_id = therapist.id

        response = client.delete(f"/api/v1/admin/therapists/{therapist_id}")

        assert response.status_code == 204

        # Verify soft-deleted
        db_session.refresh(therapist)
        assert therapist.is_active is False


class TestSpecialtyAssignment:
    """Tests for specialty assignment endpoints"""

    def test_assign_specialty(self, client, db_session: Session):
        """Assign a specialty to therapist."""
        # Create therapist
        user = User(
            neon_auth_sub="auth-1",
            email="dr@test.com",
            display_name="Dr. Test",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.flush()

        therapist = Therapist(user_id=user.id, display_name="Dr. Test", is_active=True)
        db_session.add(therapist)
        db_session.commit()
        db_session.refresh(therapist)

        # Create specialty
        specialty = TherapistSpecialty(name="Sports Rehab", is_active=True)
        db_session.add(specialty)
        db_session.commit()
        db_session.refresh(specialty)

        response = client.post(
            f"/api/v1/admin/therapists/{therapist.id}/specialties",
            json={"specialty_id": specialty.id},
        )

        assert response.status_code == 201
        assert response.json()["status"] == "success"

        # Verify assignment in database
        assignment = db_session.exec(
            select(TherapistSpecialtyMap).where(
                TherapistSpecialtyMap.therapist_id == therapist.id,
                TherapistSpecialtyMap.specialty_id == specialty.id,
            )
        ).first()
        assert assignment is not None

    def test_assign_duplicate_specialty(self, client, db_session: Session):
        """Assign duplicate specialty should fail."""
        # Create therapist
        user = User(
            neon_auth_sub="auth-1",
            email="dr@test.com",
            display_name="Dr. Test",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.flush()

        therapist = Therapist(user_id=user.id, display_name="Dr. Test", is_active=True)
        db_session.add(therapist)
        db_session.commit()
        db_session.refresh(therapist)

        # Create specialty
        specialty = TherapistSpecialty(name="Sports Rehab", is_active=True)
        db_session.add(specialty)
        db_session.commit()
        db_session.refresh(specialty)

        # First assignment
        assignment = TherapistSpecialtyMap(
            therapist_id=therapist.id, specialty_id=specialty.id
        )
        db_session.add(assignment)
        db_session.commit()

        # Try duplicate assignment
        response = client.post(
            f"/api/v1/admin/therapists/{therapist.id}/specialties",
            json={"specialty_id": specialty.id},
        )

        assert response.status_code == 400
        assert "already assigned" in response.json()["detail"].lower()

    def test_remove_specialty(self, client, db_session: Session):
        """Remove specialty from therapist."""
        # Create therapist
        user = User(
            neon_auth_sub="auth-1",
            email="dr@test.com",
            display_name="Dr. Test",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.flush()

        therapist = Therapist(user_id=user.id, display_name="Dr. Test", is_active=True)
        db_session.add(therapist)
        db_session.commit()
        db_session.refresh(therapist)

        # Create specialty
        specialty = TherapistSpecialty(name="Sports Rehab", is_active=True)
        db_session.add(specialty)
        db_session.commit()
        db_session.refresh(specialty)

        # Create assignment
        assignment = TherapistSpecialtyMap(
            therapist_id=therapist.id, specialty_id=specialty.id
        )
        db_session.add(assignment)
        db_session.commit()

        response = client.delete(
            f"/api/v1/admin/therapists/{therapist.id}/specialties/{specialty.id}"
        )

        assert response.status_code == 204

        # Verify removed
        assignment_check = db_session.exec(
            select(TherapistSpecialtyMap).where(
                TherapistSpecialtyMap.therapist_id == therapist.id,
                TherapistSpecialtyMap.specialty_id == specialty.id,
            )
        ).first()
        assert assignment_check is None

    def test_list_therapist_specialties(self, client, db_session: Session):
        """List all specialties for a therapist."""
        # Create therapist
        user = User(
            neon_auth_sub="auth-1",
            email="dr@test.com",
            display_name="Dr. Test",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.flush()

        therapist = Therapist(user_id=user.id, display_name="Dr. Test", is_active=True)
        db_session.add(therapist)
        db_session.commit()
        db_session.refresh(therapist)

        # Create specialties
        specialties = [
            TherapistSpecialty(name="Sports Rehab", is_active=True),
            TherapistSpecialty(name="Orthopedic", is_active=True),
        ]
        for spec in specialties:
            db_session.add(spec)
        db_session.commit()
        for spec in specialties:
            db_session.refresh(spec)

        # Assign both specialties
        for spec in specialties:
            assignment = TherapistSpecialtyMap(
                therapist_id=therapist.id, specialty_id=spec.id
            )
            db_session.add(assignment)
        db_session.commit()

        response = client.get(f"/api/v1/admin/therapists/{therapist.id}/specialties")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        specialty_names = {s["name"] for s in data}
        assert specialty_names == {"Sports Rehab", "Orthopedic"}


def test_pending_therapist_links_to_real_sub_on_first_login(client, db_session: Session):
    """An admin-provisioned (pending:) therapist is relinked to the real Neon sub
    by email on first login, so the created record becomes usable."""
    from app.core.auth import get_current_approved_user

    resp = client.post(
        "/api/v1/admin/therapists",
        json={
            "email": "linkme@test.com",
            "display_name": "Dr Link",
            "license_number": "PT111222",
        },
    )
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]
    assert db_session.get(User, user_id).neon_auth_sub == "pending:linkme@test.com"

    linked = get_current_approved_user(
        "therapist",
        {"user_id": "real-neon-sub-xyz", "email": "linkme@test.com"},
        db_session,
    )
    assert linked.id == user_id
    assert linked.neon_auth_sub == "real-neon-sub-xyz"


def test_create_therapist_with_offered_durations_provisions_link_less_slots(client, db_session: Session):
    """Admin create with slot_durations + payouts (no Calendly link yet) creates
    link-less event types carrying the payout (req 2.4 full create form)."""
    from app.models import TherapistEventType

    response = client.post(
        "/api/v1/admin/therapists",
        json={
            "email": "slots@test.com",
            "display_name": "Dr Slots",
            "license_number": "PT700700",
            "slot_durations": ["15", "60"],
            "slot_payouts": {"15": 20000, "60": 90000},
        },
    )
    assert response.status_code == 201
    therapist_id = response.json()["id"]

    rows = db_session.exec(
        select(TherapistEventType).where(TherapistEventType.therapist_id == therapist_id)
    ).all()
    by_duration = {r.duration_minutes: r for r in rows}
    assert set(by_duration.keys()) == {15, 60}
    assert by_duration[15].scheduling_url is None
    assert by_duration[15].payout_cents == 20000
    assert by_duration[60].payout_cents == 90000


def test_create_therapist_with_booking_links_provisions_slots(client, db_session: Session):
    """Admin create with slot_mapping (booking links, no PAT) creates bookable slots."""
    from app.models import TherapistEventType

    response = client.post(
        "/api/v1/admin/therapists",
        json={
            "email": "links@test.com",
            "display_name": "Dr Links",
            "slot_mapping": {"30": "https://calendly.com/dr/30", "45": "https://calendly.com/dr/45"},
            "slot_payouts": {"30": 30000},
        },
    )
    assert response.status_code == 201
    therapist_id = response.json()["id"]

    rows = db_session.exec(
        select(TherapistEventType).where(TherapistEventType.therapist_id == therapist_id)
    ).all()
    by_duration = {r.duration_minutes: r for r in rows}
    assert by_duration[30].scheduling_url == "https://calendly.com/dr/30"
    assert by_duration[30].payout_cents == 30000
    assert by_duration[45].scheduling_url == "https://calendly.com/dr/45"


def test_admin_update_slot_mapping_replaces_links_and_payouts(client, db_session: Session):
    """Admin edit: PUT /slot-mapping (no PAT) replaces a therapist's slots with the
    given booking links + payouts (req 2.4 edit form)."""
    from app.models import TherapistEventType

    create = client.post(
        "/api/v1/admin/therapists",
        json={"email": "editslots@test.com", "display_name": "Dr Edit"},
    )
    assert create.status_code == 201
    therapist_id = create.json()["id"]

    resp = client.put(
        f"/api/v1/admin/therapists/{therapist_id}/slot-mapping",
        json={
            "slot_mapping": {"30": "https://calendly.com/e/30", "60": "https://calendly.com/e/60"},
            "slot_payouts": {"30": 30000, "60": 90000},
        },
    )
    assert resp.status_code == 200
    by_duration = {r["duration_minutes"]: r for r in resp.json()}
    assert by_duration[30]["scheduling_url"] == "https://calendly.com/e/30"
    assert by_duration[30]["payout_cents"] == 30000
    assert by_duration[60]["payout_cents"] == 90000

    rows = db_session.exec(
        select(TherapistEventType).where(TherapistEventType.therapist_id == therapist_id)
    ).all()
    assert {r.duration_minutes for r in rows} == {30, 60}


def test_admin_set_therapist_calendly_pat(client, db_session: Session):
    """Admin can set/replace a therapist's Calendly PAT: it is validated then
    stored encrypted and the Calendly user URI is updated (req 2.4)."""
    from unittest.mock import patch

    create = client.post(
        "/api/v1/admin/therapists",
        json={"email": "pat@test.com", "display_name": "Dr PAT"},
    )
    assert create.status_code == 201
    therapist_id = create.json()["id"]

    validation = {
        "valid": True,
        "user_uri": "https://api.calendly.com/users/XYZ",
        "name": "Dr PAT",
        "email": "pat@test.com",
        "event_types_found": 0,
        "event_types": [],
        "warnings": [],
    }
    with patch(
        "app.api.v1.routes.admin.therapists.validate_calendly_pat",
        return_value=(True, validation, []),
    ), patch(
        "app.api.v1.routes.admin.therapists.encrypt_string",
        return_value="ENC(pat-token)",
    ):
        resp = client.put(
            f"/api/v1/admin/therapists/{therapist_id}/calendly-pat",
            json={"calendly_pat": "pat-token"},
        )
    assert resp.status_code == 200

    therapist = db_session.get(Therapist, therapist_id)
    db_session.refresh(therapist)
    assert therapist.calendly_pat_encrypted == "ENC(pat-token)"
    assert therapist.calendly_user_uri == "https://api.calendly.com/users/XYZ"


def test_admin_set_therapist_calendly_pat_rejects_invalid(client, db_session: Session):
    from unittest.mock import patch

    create = client.post(
        "/api/v1/admin/therapists",
        json={"email": "badpat@test.com", "display_name": "Dr Bad"},
    )
    therapist_id = create.json()["id"]

    with patch(
        "app.api.v1.routes.admin.therapists.validate_calendly_pat",
        return_value=(False, {}, ["Invalid token"]),
    ):
        resp = client.put(
            f"/api/v1/admin/therapists/{therapist_id}/calendly-pat",
            json={"calendly_pat": "bad"},
        )
    assert resp.status_code == 400
