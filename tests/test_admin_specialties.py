"""Tests for admin specialty endpoints."""

import pytest
from sqlmodel import Session, select

from app.models import TherapistSpecialty


class TestCreateSpecialty:
    """Tests for POST /admin/specialties"""

    def test_create_specialty_success(self, client, db_session: Session):
        """Successfully create a new specialty."""
        response = client.post(
            "/api/v1/admin/specialties",
            json={"name": "Sports Rehab", "description": "Sports injury treatment"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Sports Rehab"
        assert data["description"] == "Sports injury treatment"
        assert data["is_active"] is True
        assert "id" in data

        # Verify in database
        specialty = db_session.get(TherapistSpecialty, data["id"])
        assert specialty is not None
        assert specialty.name == "Sports Rehab"

    def test_create_specialty_without_description(self, client, db_session: Session):
        """Create specialty without description (optional field)."""
        response = client.post(
            "/api/v1/admin/specialties", json={"name": "Orthopedic"}
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Orthopedic"
        assert data["description"] is None

    def test_create_duplicate_specialty_name(self, client, db_session: Session):
        """Duplicate specialty name should fail."""
        # Create first specialty
        specialty = TherapistSpecialty(name="Neurological", is_active=True)
        db_session.add(specialty)
        db_session.commit()

        # Try to create duplicate
        response = client.post(
            "/api/v1/admin/specialties", json={"name": "Neurological"}
        )

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_create_specialty_empty_name(self, client, db_session: Session):
        """Empty name should fail validation."""
        response = client.post("/api/v1/admin/specialties", json={"name": ""})

        assert response.status_code == 422  # Validation error


class TestListSpecialties:
    """Tests for GET /admin/specialties"""

    def test_list_all_specialties(self, client, db_session: Session):
        """List all specialties."""
        # Create test specialties
        specialties = [
            TherapistSpecialty(name="Sports Rehab", is_active=True),
            TherapistSpecialty(name="Orthopedic", is_active=True),
            TherapistSpecialty(name="Neurological", is_active=False),
        ]
        for spec in specialties:
            db_session.add(spec)
        db_session.commit()

        response = client.get("/api/v1/admin/specialties")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        # Should be sorted by name
        assert data[0]["name"] == "Neurological"
        assert data[1]["name"] == "Orthopedic"
        assert data[2]["name"] == "Sports Rehab"

    def test_list_active_specialties_only(self, client, db_session: Session):
        """List only active specialties with filter."""
        # Create test specialties
        specialties = [
            TherapistSpecialty(name="Sports Rehab", is_active=True),
            TherapistSpecialty(name="Neurological", is_active=False),
        ]
        for spec in specialties:
            db_session.add(spec)
        db_session.commit()

        response = client.get("/api/v1/admin/specialties?active_only=true")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Sports Rehab"

    def test_list_empty_specialties(self, client, db_session: Session):
        """List when no specialties exist."""
        response = client.get("/api/v1/admin/specialties")

        assert response.status_code == 200
        assert response.json() == []


class TestGetSpecialty:
    """Tests for GET /admin/specialties/{id}"""

    def test_get_specialty_success(self, client, db_session: Session):
        """Get specialty detail."""
        specialty = TherapistSpecialty(
            name="Sports Rehab", description="Sports injuries", is_active=True
        )
        db_session.add(specialty)
        db_session.commit()
        db_session.refresh(specialty)

        response = client.get(f"/api/v1/admin/specialties/{specialty.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == specialty.id
        assert data["name"] == "Sports Rehab"
        assert data["description"] == "Sports injuries"

    def test_get_nonexistent_specialty(self, client, db_session: Session):
        """Get nonexistent specialty should return 404."""
        response = client.get("/api/v1/admin/specialties/99999")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestUpdateSpecialty:
    """Tests for PATCH /admin/specialties/{id}"""

    def test_update_specialty_name(self, client, db_session: Session):
        """Update specialty name."""
        specialty = TherapistSpecialty(name="Sports Rehab", is_active=True)
        db_session.add(specialty)
        db_session.commit()
        db_session.refresh(specialty)

        response = client.patch(
            f"/api/v1/admin/specialties/{specialty.id}",
            json={"name": "Sports Rehabilitation"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Sports Rehabilitation"

        # Verify in database
        db_session.refresh(specialty)
        assert specialty.name == "Sports Rehabilitation"

    def test_update_specialty_description(self, client, db_session: Session):
        """Update specialty description."""
        specialty = TherapistSpecialty(name="Sports Rehab", is_active=True)
        db_session.add(specialty)
        db_session.commit()
        db_session.refresh(specialty)

        response = client.patch(
            f"/api/v1/admin/specialties/{specialty.id}",
            json={"description": "New description"},
        )

        assert response.status_code == 200
        assert response.json()["description"] == "New description"

    def test_update_specialty_is_active(self, client, db_session: Session):
        """Update specialty is_active status."""
        specialty = TherapistSpecialty(name="Sports Rehab", is_active=True)
        db_session.add(specialty)
        db_session.commit()
        db_session.refresh(specialty)

        response = client.patch(
            f"/api/v1/admin/specialties/{specialty.id}", json={"is_active": False}
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_update_to_duplicate_name(self, client, db_session: Session):
        """Update to duplicate name should fail."""
        specialty1 = TherapistSpecialty(name="Sports Rehab", is_active=True)
        specialty2 = TherapistSpecialty(name="Orthopedic", is_active=True)
        db_session.add(specialty1)
        db_session.add(specialty2)
        db_session.commit()
        db_session.refresh(specialty1)
        db_session.refresh(specialty2)

        response = client.patch(
            f"/api/v1/admin/specialties/{specialty2.id}", json={"name": "Sports Rehab"}
        )

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_update_nonexistent_specialty(self, client, db_session: Session):
        """Update nonexistent specialty should return 404."""
        response = client.patch(
            "/api/v1/admin/specialties/99999", json={"name": "New Name"}
        )

        assert response.status_code == 404


class TestDeleteSpecialty:
    """Tests for DELETE /admin/specialties/{id}"""

    def test_delete_specialty_soft_delete(self, client, db_session: Session):
        """Delete should soft-delete (set is_active=false)."""
        specialty = TherapistSpecialty(name="Sports Rehab", is_active=True)
        db_session.add(specialty)
        db_session.commit()
        db_session.refresh(specialty)
        specialty_id = specialty.id

        response = client.delete(f"/api/v1/admin/specialties/{specialty_id}")

        assert response.status_code == 204

        # Verify it's soft-deleted (still in DB but inactive)
        db_session.refresh(specialty)
        assert specialty.is_active is False

        # Verify it still exists in database
        specialty_check = db_session.get(TherapistSpecialty, specialty_id)
        assert specialty_check is not None

    def test_delete_nonexistent_specialty(self, client, db_session: Session):
        """Delete nonexistent specialty should return 404."""
        response = client.delete("/api/v1/admin/specialties/99999")

        assert response.status_code == 404
