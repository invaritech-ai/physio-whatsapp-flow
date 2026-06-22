"""Tests for admin therapist endpoints."""

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.auth import get_current_admin, get_current_approved_user
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


class TestPendingAccountLinking:
    """First-login linking of admin-provisioned (pending:) therapist accounts."""

    def test_first_login_links_pending_account_by_email(self, db_session: Session):
        provisioned = User(
            neon_auth_sub="pending:linkme@test.com",
            email="linkme@test.com",
            display_name="Dr. Link",
            role="therapist",
            is_active=True,
        )
        db_session.add(provisioned)
        db_session.commit()
        db_session.refresh(provisioned)

        resolved = get_current_approved_user(
            required_role="therapist",
            current_user={"user_id": "real-neon-sub-xyz", "email": "linkme@test.com"},
            db=db_session,
        )

        assert resolved.id == provisioned.id
        assert resolved.neon_auth_sub == "real-neon-sub-xyz"

    def test_login_does_not_overwrite_non_pending_account(self, db_session: Session):
        existing = User(
            neon_auth_sub="real-existing-sub",
            email="solid@test.com",
            display_name="Dr. Solid",
            role="therapist",
            is_active=True,
        )
        db_session.add(existing)
        db_session.commit()
        db_session.refresh(existing)

        # Unknown sub but colliding email must NOT relink a real account.
        with pytest.raises(HTTPException) as exc:
            get_current_approved_user(
                required_role="therapist",
                current_user={"user_id": "intruder-sub", "email": "solid@test.com"},
                db=db_session,
            )
        assert exc.value.status_code == 403

        refreshed = db_session.get(User, existing.id)
        assert refreshed.neon_auth_sub == "real-existing-sub"


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

    def test_create_therapist_without_neon_auth_sub_uses_pending_sentinel(
        self, client, db_session: Session
    ):
        """Admin-provisioned therapist (no neon_auth_sub) gets a pending: sentinel sub."""
        response = client.post(
            "/api/v1/admin/therapists",
            json={
                "email": "Provisioned@Test.com",
                "display_name": "Dr. Provisioned",
                "license_number": "PT-555",
                "is_female": True,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["is_active"] is True
        assert data["is_female"] is True

        user = db_session.get(User, data["user_id"])
        assert user is not None
        assert user.role == "therapist"
        # Sentinel keyed by normalized (lowercased) email.
        assert user.neon_auth_sub == "pending:provisioned@test.com"

    def test_create_therapist_with_calendly_pat_provisions_calendly(
        self, client, db_session: Session, monkeypatch
    ):
        """When a Calendly PAT is supplied, the PAT is validated + stored and event types synced."""
        monkeypatch.setattr(
            "app.api.v1.routes.admin.therapists.validate_calendly_pat",
            lambda pat: (True, {"user_uri": "https://api.calendly.com/users/ABC"}, []),
        )
        synced = {"called": False}

        def fake_sync(db, therapist, calendly_pat=None):
            synced["called"] = True
            return [], []

        monkeypatch.setattr("app.api.v1.routes.admin.therapists.sync_event_types", fake_sync)

        response = client.post(
            "/api/v1/admin/therapists",
            json={
                "email": "cal@test.com",
                "display_name": "Dr. Cal",
                "calendly_pat": "pat-token-123",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["calendly_user_uri"] == "https://api.calendly.com/users/ABC"
        assert synced["called"] is True

        therapist = db_session.get(Therapist, data["id"])
        assert therapist.calendly_pat_encrypted is not None
        assert therapist.calendly_pat_encrypted != "pat-token-123"  # stored encrypted

    def test_admin_validate_calendly_returns_event_types(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.routes.admin.therapists.validate_calendly_pat",
            lambda pat: (
                True,
                {
                    "valid": True,
                    "user_uri": "https://api.calendly.com/users/ABC",
                    "name": "Dr. Cal",
                    "email": "cal@test.com",
                    "event_types_found": 1,
                    "event_types": [
                        {
                            "calendly_event_type_uri": "https://api.calendly.com/event_types/E30",
                            "duration_minutes": 30,
                            "name": "30 min",
                            "scheduling_url": "https://calendly.com/cal/30",
                        }
                    ],
                    "warnings": [],
                },
                [],
            ),
        )
        response = client.post(
            "/api/v1/admin/therapists/validate-calendly",
            json={"calendly_pat": "good-token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["event_types"][0]["duration_minutes"] == 30

    def test_create_therapist_with_slot_mapping_creates_event_types(
        self, client, db_session: Session, monkeypatch
    ):
        from app.models import TherapistEventType

        monkeypatch.setattr(
            "app.api.v1.routes.admin.therapists.validate_calendly_pat",
            lambda pat: (
                True,
                {
                    "valid": True,
                    "user_uri": "https://api.calendly.com/users/ABC",
                    "name": "Dr. Map",
                    "email": "map@test.com",
                    "event_types_found": 2,
                    "event_types": [
                        {
                            "calendly_event_type_uri": "https://api.calendly.com/event_types/E30",
                            "duration_minutes": 30,
                            "name": "30 min",
                            "scheduling_url": "https://calendly.com/map/30",
                        },
                        {
                            "calendly_event_type_uri": "https://api.calendly.com/event_types/E45",
                            "duration_minutes": 45,
                            "name": "45 min",
                            "scheduling_url": "https://calendly.com/map/45",
                        },
                    ],
                    "warnings": [],
                },
                [],
            ),
        )

        response = client.post(
            "/api/v1/admin/therapists",
            json={
                "email": "map@test.com",
                "display_name": "Dr. Map",
                "calendly_pat": "good-token",
                "slot_mapping": {
                    "30": "https://calendly.com/map/30",
                    "45": "https://calendly.com/map/45",
                },
            },
        )

        assert response.status_code == 201
        data = response.json()
        rows = db_session.exec(
            select(TherapistEventType)
            .where(TherapistEventType.therapist_id == data["id"])
            .order_by(TherapistEventType.duration_minutes)
        ).all()
        assert [r.duration_minutes for r in rows] == [30, 45]
        assert rows[0].calendly_event_type_uri == "https://api.calendly.com/event_types/E30"
        assert rows[1].scheduling_url == "https://calendly.com/map/45"

    def test_create_therapist_with_slot_durations_no_links(self, client, db_session: Session):
        """Admin can record offered session lengths (+ pay) with no booking link yet."""
        from app.models import TherapistEventType

        response = client.post(
            "/api/v1/admin/therapists",
            json={
                "email": "durations@test.com",
                "display_name": "Dr. Durations",
                "slot_durations": ["30", "60"],
                "slot_payouts": {"30": 40000},
            },
        )

        assert response.status_code == 201
        data = response.json()
        rows = db_session.exec(
            select(TherapistEventType)
            .where(TherapistEventType.therapist_id == data["id"])
            .order_by(TherapistEventType.duration_minutes)
        ).all()
        assert [r.duration_minutes for r in rows] == [30, 60]
        # No booking link / Calendly event yet — added later from the edit screen.
        assert all(r.scheduling_url is None for r in rows)
        assert all(r.calendly_event_type_uri is None for r in rows)
        assert rows[0].payout_cents == 40000
        assert rows[1].payout_cents is None

    def test_create_therapist_with_invalid_calendly_pat_rolls_back(
        self, client, db_session: Session, monkeypatch
    ):
        """Invalid PAT returns 400 and leaves no orphaned user/therapist."""
        monkeypatch.setattr(
            "app.api.v1.routes.admin.therapists.validate_calendly_pat",
            lambda pat: (False, {}, ["Invalid Calendly token"]),
        )

        response = client.post(
            "/api/v1/admin/therapists",
            json={
                "email": "badcal@test.com",
                "display_name": "Dr. BadCal",
                "calendly_pat": "bad-token",
            },
        )

        assert response.status_code == 400
        assert "Invalid Calendly token" in response.json()["detail"]
        # Rolled back: no user persisted for this email.
        assert db_session.exec(select(User).where(User.email == "badcal@test.com")).first() is None

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
