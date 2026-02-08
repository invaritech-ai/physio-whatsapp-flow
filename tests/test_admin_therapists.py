"""Tests for admin therapist endpoints."""

import pytest
from sqlmodel import Session, select

from app.models import Therapist, TherapistSpecialty, TherapistSpecialtyMap, User


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
        assert data["calendly_user_uri"] is None

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

        users = db_session.exec(select(User)).all()
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
