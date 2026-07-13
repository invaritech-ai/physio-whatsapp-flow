"""Tests for therapist self-service onboarding endpoints."""

from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.models import (
    AccessRequest,
    Therapist,
    TherapistEventType,
    TherapistSpecialty,
    TherapistSpecialtyMap,
    User,
)
from app.services.therapist_onboarding import sync_event_types


# Mock encryption functions for tests (we don't need to test actual encryption)
@pytest.fixture(autouse=True)
def mock_encryption():
    """Mock encryption functions to return plaintext (for testing only)."""
    with patch("app.services.therapist_onboarding.encrypt_string") as mock_encrypt, \
         patch("app.services.therapist_onboarding.decrypt_string") as mock_decrypt:
        # Encryption just returns the input (no actual encryption in tests)
        mock_encrypt.side_effect = lambda x: f"encrypted_{x}"
        mock_decrypt.side_effect = lambda x: x.replace("encrypted_", "")
        yield mock_encrypt, mock_decrypt


@pytest.fixture(name="therapist_user")
def therapist_user_fixture(db_session: Session):
    """Create a therapist user for testing."""
    user = User(
        neon_auth_sub="therapist-sub-123",
        email="therapist@test.com",
        display_name="Dr. Test Therapist",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(name="therapist_no_uri")
def therapist_no_uri_fixture(db_session: Session, therapist_user: User):
    """Create a therapist without Calendly URI (not onboarded)."""
    therapist = Therapist(
        user_id=therapist_user.id,
        display_name="Dr. Test Therapist",
        license_number="PT-ONBOARD-001",
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return therapist


@pytest.fixture(name="therapist_with_uri")
def therapist_with_uri_fixture(db_session: Session, therapist_user: User):
    """Create a therapist with Calendly URI (onboarded)."""
    therapist = Therapist(
        user_id=therapist_user.id,
        display_name="Dr. Test Therapist",
        license_number="PT-ONBOARD-002",
        calendly_user_uri="https://api.calendly.com/users/TEST123",
        is_active=True,
    )
    db_session.add(therapist)
    db_session.commit()
    db_session.refresh(therapist)
    return therapist


@pytest.fixture(name="sample_specialties_onboarding")
def sample_specialties_onboarding_fixture(db_session: Session):
    """Create sample specialties for onboarding tests."""
    specialties = [
        TherapistSpecialty(name="Sports Rehab", is_active=True),
        TherapistSpecialty(name="Women's Health", is_active=True),
        TherapistSpecialty(name="Pediatric", is_active=True),
    ]
    for spec in specialties:
        db_session.add(spec)
    db_session.commit()
    for spec in specialties:
        db_session.refresh(spec)
    return specialties


@pytest.fixture(name="mock_jwt_therapist")
def mock_jwt_therapist_fixture(therapist_user: User):
    """Mock JWT validation to return therapist user."""
    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": therapist_user.neon_auth_sub,
            "email": therapist_user.email,
        }
        yield mock_verify


@pytest.fixture(name="mock_calendly_valid")
def mock_calendly_valid_fixture():
    """Mock valid Calendly API responses."""
    user_info_response = {
        "uri": "https://api.calendly.com/users/TESTUSER123",
        "name": "Dr. Test Therapist",
        "email": "therapist@test.com",
    }

    event_types_response = [
        {
            "uri": "https://api.calendly.com/event_types/30MIN",
            "name": "30 Minute Session",
            "duration": 30,
            "scheduling_url": "https://calendly.com/test/30min",
            "active": True,
        },
        {
            "uri": "https://api.calendly.com/event_types/45MIN",
            "name": "45 Minute Session",
            "duration": 45,
            "scheduling_url": "https://calendly.com/test/45min",
            "active": True,
        },
        {
            "uri": "https://api.calendly.com/event_types/60MIN",
            "name": "60 Minute Session",
            "duration": 60,
            "scheduling_url": "https://calendly.com/test/60min",
            "active": True,
        },
    ]

    # Patch where functions are imported and used (in therapist_onboarding module)
    with patch("app.services.therapist_onboarding.get_user_info_with_pat") as mock_user, \
         patch("app.services.therapist_onboarding.get_event_types_with_pat") as mock_events:
        mock_user.return_value = user_info_response
        mock_events.return_value = event_types_response
        yield mock_user, mock_events


class TestCompleteOnboarding:
    """Tests for POST /therapist/onboarding/complete"""

    def test_complete_onboarding_success(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
        mock_calendly_valid,
    ):
        """Successfully complete therapist onboarding."""
        response = client.post(
            "/api/v1/therapist/onboarding/complete",
            json={
                "calendly_pat": "valid_token_123",
                "specialty_ids": [1, 2],
            },
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["therapist_id"] == therapist_no_uri.id
        assert data["display_name"] == "Dr. Test Therapist"
        assert data["calendly_user_uri"] == "https://api.calendly.com/users/TESTUSER123"
        assert data["is_active"] is True
        assert data["event_types_synced"] == 3
        assert len(data["specialties"]) == 2
        assert len(data["event_types"]) == 3

        # Verify database records
        db_session.refresh(therapist_no_uri)
        assert therapist_no_uri.calendly_user_uri is not None
        assert therapist_no_uri.is_active is True

    def test_complete_onboarding_invalid_token(
        self,
        client,
        therapist_no_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
    ):
        """Fail with invalid Calendly token."""
        with patch("app.services.therapist_onboarding.get_user_info_with_pat") as mock_user:
            mock_user.return_value = None

            response = client.post(
                "/api/v1/therapist/onboarding/complete",
                json={
                    "calendly_pat": "invalid_token",
                    "specialty_ids": [1],
                },
                headers={"Authorization": "Bearer test-token"},
            )

            assert response.status_code == 400
            assert "Invalid Calendly token" in response.json()["detail"]

    def test_complete_onboarding_already_onboarded(
        self,
        client,
        therapist_with_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
        mock_calendly_valid,
    ):
        """Fail if therapist already has Calendly URI."""
        response = client.post(
            "/api/v1/therapist/onboarding/complete",
            json={
                "calendly_pat": "valid_token_123",
                "specialty_ids": [1],
            },
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400
        assert "already has Calendly URI" in response.json()["detail"]

    def test_complete_onboarding_allows_partial_event_types(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
    ):
        """Allow onboarding when Calendly has at least one readable event type."""
        user_info = {
            "uri": "https://api.calendly.com/users/TESTUSER123",
            "name": "Dr. Test",
            "email": "test@test.com",
        }
        event_types = [
            {
                "uri": "https://api.calendly.com/event_types/30MIN",
                "duration": 30,
                "scheduling_url": "https://calendly.com/test/30min",
                "active": True,
            }
        ]

        with patch("app.services.therapist_onboarding.get_user_info_with_pat") as mock_user, \
             patch("app.services.therapist_onboarding.get_event_types_with_pat") as mock_events:
            mock_user.return_value = user_info
            mock_events.return_value = event_types

            response = client.post(
                "/api/v1/therapist/onboarding/complete",
                json={
                    "calendly_pat": "valid_token_123",
                    "specialty_ids": [1],
                },
                headers={"Authorization": "Bearer test-token"},
            )

            assert response.status_code == 201
            data = response.json()
            assert data["event_types_synced"] == 1
            assert len(data["event_types"]) == 1

            db_session.refresh(therapist_no_uri)
            assert therapist_no_uri.calendly_user_uri == user_info["uri"]
            assert therapist_no_uri.is_active is True

    def test_complete_onboarding_invalid_specialties(
        self,
        client,
        therapist_no_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
        mock_calendly_valid,
    ):
        """Fail if specialty IDs don't exist."""
        response = client.post(
            "/api/v1/therapist/onboarding/complete",
            json={
                "calendly_pat": "valid_token_123",
                "specialty_ids": [999],  # Non-existent ID
            },
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400
        assert "Invalid specialty IDs" in response.json()["detail"]

    def test_complete_onboarding_requires_license_number(
        self,
        client,
        db_session: Session,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_calendly_valid,
    ):
        user = User(
            neon_auth_sub="therapist-no-license-sub",
            email="therapist-no-license@test.com",
            display_name="No License Therapist",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        therapist = Therapist(
            user_id=user.id,
            display_name="No License Therapist",
            is_active=True,
        )
        db_session.add(therapist)
        db_session.commit()

        with patch("app.core.auth._verify_neon_token") as mock_verify:
            mock_verify.return_value = {
                "sub": user.neon_auth_sub,
                "email": user.email,
            }
            response = client.post(
                "/api/v1/therapist/onboarding/complete",
                json={
                    "calendly_pat": "valid_token_123",
                    "specialty_ids": [1],
                },
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "license_number_required"


class TestOnboardingStatus:
    """Tests for GET /therapist/onboarding/status"""

    def test_status_not_onboarded(
        self,
        client,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        """Status shows incomplete onboarding."""
        response = client.get(
            "/api/v1/therapist/onboarding/status",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_onboarded"] is False
        assert data["has_license_number"] is True
        assert data["has_calendly_uri"] is False
        assert data["has_event_types"] is False
        assert data["has_specialties"] is False
        assert data["is_active"] is True
        assert "calendly_setup" in data["missing_steps"]
        assert "event_types" in data["missing_steps"]
        assert "specialties" not in data["missing_steps"]
        assert "license_number" not in data["missing_steps"]

    def test_status_fully_onboarded(
        self,
        client,
        db_session: Session,
        therapist_with_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
    ):
        """Status shows complete onboarding."""
        # Add one active mapped event type
        db_session.add(
            TherapistEventType(
                therapist_id=therapist_with_uri.id,
                calendly_event_type_uri="https://api.calendly.com/event_types/45MIN",
                duration_minutes=45,
                scheduling_url="https://calendly.com/test/45min",
                is_active=True,
            )
        )

        # Add specialties
        mapping = TherapistSpecialtyMap(
            therapist_id=therapist_with_uri.id,
            specialty_id=sample_specialties_onboarding[0].id,
        )
        db_session.add(mapping)
        db_session.commit()

        response = client.get(
            "/api/v1/therapist/onboarding/status",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_onboarded"] is True
        assert data["has_license_number"] is True
        assert data["has_calendly_uri"] is True
        assert data["has_event_types"] is True
        assert data["has_specialties"] is True
        assert data["has_slot_mapping"] is True
        assert data["event_types_count"] == 1
        assert data["specialties_count"] == 1
        assert data["missing_steps"] == []

    def test_status_missing_license_number_step(
        self,
        client,
        db_session: Session,
    ):
        user = User(
            neon_auth_sub="therapist-missing-license-sub",
            email="therapist-missing-license@test.com",
            display_name="Missing License Therapist",
            role="therapist",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        therapist = Therapist(
            user_id=user.id,
            display_name="Missing License Therapist",
            is_active=True,
        )
        db_session.add(therapist)
        db_session.commit()

        with patch("app.core.auth._verify_neon_token") as mock_verify:
            mock_verify.return_value = {
                "sub": user.neon_auth_sub,
                "email": user.email,
            }
            response = client.get(
                "/api/v1/therapist/onboarding/status",
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["has_license_number"] is False
        assert "license_number" in data["missing_steps"]


class TestValidateCalendly:
    """Tests for POST /therapist/onboarding/validate-calendly"""

    def test_validate_success_no_warnings(
        self,
        client,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
        mock_calendly_valid,
    ):
        """Validate PAT successfully with all event types."""
        response = client.post(
            "/api/v1/therapist/onboarding/validate-calendly",
            json={"calendly_pat": "valid_token_123"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["user_uri"] == "https://api.calendly.com/users/TESTUSER123"
        assert data["name"] == "Dr. Test Therapist"
        assert data["email"] == "therapist@test.com"
        assert data["event_types_found"] == 3
        assert len(data["event_types"]) == 3
        assert data["warnings"] == []

    def test_validate_with_partial_event_types_has_no_duration_warnings(
        self,
        client,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        """Validate PAT without warning on missing fixed durations."""
        user_info = {
            "uri": "https://api.calendly.com/users/TESTUSER123",
            "name": "Dr. Test",
            "email": "test@test.com",
        }
        event_types = [
            {
                "uri": "https://api.calendly.com/event_types/30MIN",
                "duration": 30,
                "name": "30 Min Session",
                "scheduling_url": "https://calendly.com/test/30min",
                "active": True,
            }
        ]

        with patch("app.services.therapist_onboarding.get_user_info_with_pat") as mock_user, \
             patch("app.services.therapist_onboarding.get_event_types_with_pat") as mock_events:
            mock_user.return_value = user_info
            mock_events.return_value = event_types

            response = client.post(
                "/api/v1/therapist/onboarding/validate-calendly",
                json={"calendly_pat": "valid_token_123"},
                headers={"Authorization": "Bearer test-token"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is True
            assert data["event_types_found"] == 1
            assert data["warnings"] == []

    def test_validate_invalid_token(
        self,
        client,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        """Fail with invalid Calendly token."""
        with patch("app.services.therapist_onboarding.get_user_info_with_pat") as mock_user:
            mock_user.return_value = None

            response = client.post(
                "/api/v1/therapist/onboarding/validate-calendly",
                json={"calendly_pat": "invalid_token"},
                headers={"Authorization": "Bearer test-token"},
            )

            assert response.status_code == 400
            assert "Invalid Calendly token" in response.json()["detail"]

    def test_validate_stored_pat_success(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        therapist_no_uri.calendly_pat_encrypted = "encrypted_valid_token_123"
        db_session.add(therapist_no_uri)
        db_session.commit()

        with patch("app.api.v1.routes.therapist.onboarding.decrypt_string", return_value="valid_token_123"), \
             patch("app.services.therapist_onboarding.get_user_info_with_pat") as mock_user, \
             patch("app.services.therapist_onboarding.get_event_types_with_pat") as mock_events:
            mock_user.return_value = {
                "uri": "https://api.calendly.com/users/TESTUSER123",
                "name": "Dr. Test Therapist",
                "email": "therapist@test.com",
            }
            mock_events.return_value = [
                {
                    "uri": "https://api.calendly.com/event_types/30MIN",
                    "duration": 30,
                    "name": "30 Minute Session",
                    "scheduling_url": "https://calendly.com/test/30min",
                    "active": True,
                }
            ]

            response = client.post(
                "/api/v1/therapist/onboarding/validate-calendly/stored",
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["event_types_found"] == 1
        assert data["event_types"][0]["scheduling_url"] == "https://calendly.com/test/30min"

    def test_validate_stored_pat_missing(self, client, therapist_no_uri: Therapist, mock_jwt_therapist):
        response = client.post(
            "/api/v1/therapist/onboarding/validate-calendly/stored",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Calendly PAT not configured. Connect Calendly first."

    def test_validate_stored_pat_invalid_ciphertext(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        therapist_no_uri.calendly_pat_encrypted = "not-a-valid-fernet-token"
        db_session.add(therapist_no_uri)
        db_session.commit()

        response = client.post(
            "/api/v1/therapist/onboarding/validate-calendly/stored",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Stored Calendly token is invalid"


class TestSyncEventTypes:
    """Tests for POST /therapist/sync-event-types"""

    def test_sync_event_types_success(
        self,
        client,
        db_session: Session,
        therapist_with_uri: Therapist,
        mock_jwt_therapist,
    ):
        """Successfully sync event types."""
        # Mock Calendly get_event_types (org-level token)
        event_types = [
            {
                "uri": "https://api.calendly.com/event_types/30MIN",
                "duration": 30,
                "scheduling_url": "https://calendly.com/test/30min",
                "active": True,
            },
            {
                "uri": "https://api.calendly.com/event_types/45MIN",
                "duration": 45,
                "scheduling_url": "https://calendly.com/test/45min",
                "active": True,
            },
        ]

        with patch("app.services.calendly.get_event_types") as mock_events:
            mock_events.return_value = event_types

            response = client.post(
                "/api/v1/therapist/sync-event-types",
                headers={"Authorization": "Bearer test-token"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["event_types_synced"] == 2
            assert len(data["event_types"]) == 2

            # Verify database records created
            from sqlmodel import select
            stmt = select(TherapistEventType).where(
                TherapistEventType.therapist_id == therapist_with_uri.id
            )
            db_event_types = db_session.exec(stmt).all()
            assert len(db_event_types) == 2

    def test_sync_without_calendly_uri(
        self,
        client,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        """Fail if therapist has no Calendly URI."""
        response = client.post(
            "/api/v1/therapist/sync-event-types",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400
        assert "does not have Calendly URI" in response.json()["detail"]


class TestSaveCalendly:
    """Tests for POST /therapist/onboarding/calendly"""

    def test_save_calendly_accepts_mismatched_native_durations_for_business_slots(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        user_info = {
            "uri": "https://api.calendly.com/users/TESTUSER123",
            "name": "Dr. Test",
            "email": "test@test.com",
        }
        event_types = [
            {
                "uri": "https://api.calendly.com/event_types/45MIN",
                "duration": 45,
                "name": "45 Min Session",
                "scheduling_url": "https://calendly.com/test/45min",
                "active": True,
            },
            {
                "uri": "https://api.calendly.com/event_types/75MIN",
                "duration": 75,
                "name": "75 Min Session",
                "scheduling_url": "https://calendly.com/test/75min",
                "active": True,
            },
        ]

        with patch("app.services.therapist_onboarding.get_user_info_with_pat") as mock_user, \
             patch("app.services.therapist_onboarding.get_event_types_with_pat") as mock_events:
            mock_user.return_value = user_info
            mock_events.return_value = event_types

            response = client.post(
                "/api/v1/therapist/onboarding/calendly",
                json={
                    "calendly_pat": "valid_token_123",
                    "slot_mapping": {
                        "30": "https://calendly.com/test/45min",
                        "45": "https://calendly.com/test/75min",
                    },
                },
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is True
        assert [item["duration_minutes"] for item in data["slot_mapping"]] == [30, 45]
        # URI derived by matching scheduling URL against Calendly event type list
        assert [item["calendly_event_type_uri"] for item in data["slot_mapping"]] == [
            "https://api.calendly.com/event_types/45MIN",
            "https://api.calendly.com/event_types/75MIN",
        ]

        stmt = select(TherapistEventType).where(
            TherapistEventType.therapist_id == therapist_no_uri.id
        ).order_by(TherapistEventType.duration_minutes.asc())
        mapped_event_types = db_session.exec(stmt).all()
        assert [item.duration_minutes for item in mapped_event_types] == [30, 45]
        assert [item.scheduling_url for item in mapped_event_types] == [
            "https://calendly.com/test/45min",
            "https://calendly.com/test/75min",
        ]
        assert [item.calendly_event_type_uri for item in mapped_event_types] == [
            "https://api.calendly.com/event_types/45MIN",
            "https://api.calendly.com/event_types/75MIN",
        ]

    def test_save_calendly_requires_30_and_45_business_slots(
        self,
        client,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        response = client.post(
            "/api/v1/therapist/onboarding/calendly",
            json={
                "calendly_pat": "valid_token_123",
                "slot_mapping": {
                    "30": "https://api.calendly.com/event_types/45MIN",
                    "75": "https://api.calendly.com/event_types/75MIN",
                },
            },
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 422
        assert "Missing required durations: 45" in str(response.json())

    def test_save_calendly_allows_same_calendly_uri_for_30_and_45(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        user_info = {
            "uri": "https://api.calendly.com/users/TESTUSER123",
            "name": "Dr. Test",
            "email": "test@test.com",
        }
        event_types = [
            {
                "uri": "https://api.calendly.com/event_types/SHARED",
                "duration": 45,
                "name": "Shared Demo Session",
                "scheduling_url": "https://calendly.com/test/shared",
                "active": True,
            },
        ]

        with patch("app.services.therapist_onboarding.get_user_info_with_pat") as mock_user, \
             patch("app.services.therapist_onboarding.get_event_types_with_pat") as mock_events:
            mock_user.return_value = user_info
            mock_events.return_value = event_types

            response = client.post(
                "/api/v1/therapist/onboarding/calendly",
                json={
                    "calendly_pat": "valid_token_123",
                    "slot_mapping": {
                        "30": "https://calendly.com/test/shared",
                        "45": "https://calendly.com/test/shared",
                    },
                },
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert [item["duration_minutes"] for item in data["slot_mapping"]] == [30, 45]
        # Same scheduling URL → same derived event type URI for both slots
        assert [item["calendly_event_type_uri"] for item in data["slot_mapping"]] == [
            "https://api.calendly.com/event_types/SHARED",
            "https://api.calendly.com/event_types/SHARED",
        ]

        stmt = select(TherapistEventType).where(
            TherapistEventType.therapist_id == therapist_no_uri.id
        ).order_by(TherapistEventType.duration_minutes.asc())
        mapped_event_types = db_session.exec(stmt).all()
        assert [item.duration_minutes for item in mapped_event_types] == [30, 45]
        assert [item.scheduling_url for item in mapped_event_types] == [
            "https://calendly.com/test/shared",
            "https://calendly.com/test/shared",
        ]
        assert [item.calendly_event_type_uri for item in mapped_event_types] == [
            "https://api.calendly.com/event_types/SHARED",
            "https://api.calendly.com/event_types/SHARED",
        ]

    def test_save_calendly_rejects_unknown_event_type_uri(
        self,
        client,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        with patch("app.services.therapist_onboarding.get_user_info_with_pat") as mock_user, \
             patch("app.services.therapist_onboarding.get_event_types_with_pat") as mock_events:
            mock_user.return_value = {
                "uri": "https://api.calendly.com/users/TESTUSER123",
                "name": "Dr. Test",
                "email": "test@test.com",
            }
            mock_events.return_value = [
                {
                    "uri": "https://api.calendly.com/event_types/KNOWN",
                    "duration": 45,
                    "name": "Known Event",
                    "scheduling_url": "https://calendly.com/test/known",
                    "active": True,
                }
            ]

            response = client.post(
                "/api/v1/therapist/onboarding/calendly",
                json={
                    "calendly_pat": "valid_token_123",
                    "slot_mapping": {
                        "30": "https://api.calendly.com/event_types/UNKNOWN",
                        "45": "https://calendly.com/test/known",
                    },
                },
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 400
        assert "Unknown Calendly event type URI in slot mapping" in response.json()["detail"]

    def test_save_calendly_accepts_event_type_uri_payload_for_backward_compat(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        user_info = {
            "uri": "https://api.calendly.com/users/TESTUSER123",
            "name": "Dr. Test",
            "email": "test@test.com",
        }
        event_types = [
            {
                "uri": "https://api.calendly.com/event_types/45MIN",
                "duration": 45,
                "name": "45 Min Session",
                "scheduling_url": "https://calendly.com/test/45min",
                "active": True,
            },
        ]

        with patch("app.services.therapist_onboarding.get_user_info_with_pat") as mock_user, \
             patch("app.services.therapist_onboarding.get_event_types_with_pat") as mock_events:
            mock_user.return_value = user_info
            mock_events.return_value = event_types

            response = client.post(
                "/api/v1/therapist/onboarding/calendly",
                json={
                    "calendly_pat": "valid_token_123",
                    "slot_mapping": {
                        "30": "https://api.calendly.com/event_types/45MIN",
                        "45": "https://api.calendly.com/event_types/45MIN",
                    },
                },
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert [item["scheduling_url"] for item in data["slot_mapping"]] == [
            "https://calendly.com/test/45min",
            "https://calendly.com/test/45min",
        ]
        assert [item["calendly_event_type_uri"] for item in data["slot_mapping"]] == [
            "https://api.calendly.com/event_types/45MIN",
            "https://api.calendly.com/event_types/45MIN",
        ]


class TestUpdateProfile:
    """Tests for PATCH /therapist/onboarding/profile"""

    def test_update_profile_persists_license_number(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        response = client.patch(
            "/api/v1/therapist/onboarding/profile",
            json={
                "display_name": "Dr. Updated",
                "license_number": " pt 203315 ",
            },
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["display_name"] == "Dr. Updated"
        assert data["license_number"] == "PT 203315"

        db_session.refresh(therapist_no_uri)
        assert therapist_no_uri.display_name == "Dr. Updated"
        assert therapist_no_uri.license_number == "PT 203315"

    def test_update_profile_duplicate_license_number_fails(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        other_user = User(
            neon_auth_sub="therapist-other-license-sub",
            email="therapist-other-license@test.com",
            display_name="Other Therapist",
            role="therapist",
            is_active=True,
        )
        db_session.add(other_user)
        db_session.commit()
        db_session.refresh(other_user)

        other_therapist = Therapist(
            user_id=other_user.id,
            display_name="Other Therapist",
            license_number="PT-CLASH-1",
            is_active=True,
        )
        db_session.add(other_therapist)
        db_session.commit()

        response = client.patch(
            "/api/v1/therapist/onboarding/profile",
            json={
                "display_name": "Dr. Updated",
                "license_number": "pt-clash-1",
            },
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "license_number_already_exists"


class TestUpdateSlotMapping:
    def test_update_slot_mapping_rejects_unknown_event_type_uri(
        self,
        client,
        db_session: Session,
        therapist_with_uri: Therapist,
        mock_jwt_therapist,
    ):
        db_session.add(
            TherapistEventType(
                therapist_id=therapist_with_uri.id,
                calendly_event_type_uri="https://api.calendly.com/event_types/KNOWN",
                duration_minutes=30,
                scheduling_url="https://calendly.com/test/known",
                is_active=True,
            )
        )
        db_session.commit()

        response = client.patch(
            "/api/v1/therapist/onboarding/slot-mapping",
            json={
                "slot_mapping": {
                    "30": "https://api.calendly.com/event_types/UNKNOWN",
                    "45": "https://calendly.com/test/known",
                }
            },
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400
        assert "Unknown Calendly event type URI in slot mapping" in response.json()["detail"]


class TestSyncEventTypesSharedUri:
    """Tests for Calendly event-type resync behavior after explicit slot mapping."""

    def test_sync_event_types_preserves_business_durations_for_shared_uri(
        self,
        db_session: Session,
        therapist_with_uri: Therapist,
    ):
        therapist_with_uri.calendly_pat_encrypted = "encrypted_pat"
        db_session.add(therapist_with_uri)
        db_session.commit()

        db_session.add(
            TherapistEventType(
                therapist_id=therapist_with_uri.id,
                calendly_event_type_uri="https://api.calendly.com/event_types/SHARED_SYNC",
                duration_minutes=30,
                scheduling_url="https://calendly.com/test/shared-old",
                is_active=True,
            )
        )
        db_session.add(
            TherapistEventType(
                therapist_id=therapist_with_uri.id,
                calendly_event_type_uri="https://api.calendly.com/event_types/SHARED_SYNC",
                duration_minutes=45,
                scheduling_url="https://calendly.com/test/shared-old",
                is_active=True,
            )
        )
        db_session.commit()

        with patch("app.services.therapist_onboarding.decrypt_string", return_value="plain_pat"), \
             patch(
                 "app.services.therapist_onboarding.get_event_types_with_pat",
                 return_value=[
                     {
                         "uri": "https://api.calendly.com/event_types/SHARED_SYNC",
                         "duration": 75,
                         "scheduling_url": "https://calendly.com/test/shared-new",
                         "active": True,
                     }
                 ],
             ):
            synced, errors = sync_event_types(db_session, therapist_with_uri)

        assert errors == []
        assert [item["duration_minutes"] for item in synced] == [30, 45]

        rows = db_session.exec(
            select(TherapistEventType)
            .where(TherapistEventType.therapist_id == therapist_with_uri.id)
            .order_by(TherapistEventType.duration_minutes.asc())
        ).all()
        assert [row.duration_minutes for row in rows] == [30, 45]
        assert all(row.scheduling_url == "https://calendly.com/test/shared-new" for row in rows)
        assert all(row.is_active is True for row in rows)


class TestUpdateSpecialties:
    """Tests for PATCH /therapist/specialties"""

    def test_update_specialties_success(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
    ):
        """Successfully update therapist specialties."""
        response = client.patch(
            "/api/v1/therapist/specialties",
            json={"specialty_ids": [1, 2]},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["specialties"]) == 2
        assert data["specialties"][0]["id"] == 1
        assert data["specialties"][1]["id"] == 2

        # Verify database mappings
        from sqlmodel import select
        stmt = select(TherapistSpecialtyMap).where(
            TherapistSpecialtyMap.therapist_id == therapist_no_uri.id
        )
        mappings = db_session.exec(stmt).all()
        assert len(mappings) == 2

    def test_update_specialties_replace_existing(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
    ):
        """Replace existing specialties with new ones."""
        # Add initial specialty
        mapping = TherapistSpecialtyMap(
            therapist_id=therapist_no_uri.id,
            specialty_id=1,
        )
        db_session.add(mapping)
        db_session.commit()

        # Replace with new specialty
        response = client.patch(
            "/api/v1/therapist/specialties",
            json={"specialty_ids": [2, 3]},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["specialties"]) == 2

        # Verify old mapping deleted, new ones created
        from sqlmodel import select
        stmt = select(TherapistSpecialtyMap).where(
            TherapistSpecialtyMap.therapist_id == therapist_no_uri.id
        )
        mappings = db_session.exec(stmt).all()
        assert len(mappings) == 2
        assert all(m.specialty_id in [2, 3] for m in mappings)

    def test_update_specialties_keeps_existing_and_adds_new_without_duplicate_error(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
    ):
        """Keep an existing specialty and add another one without unique-constraint failure."""
        existing_mapping = TherapistSpecialtyMap(
            therapist_id=therapist_no_uri.id,
            specialty_id=1,
        )
        db_session.add(existing_mapping)
        db_session.commit()

        response = client.patch(
            "/api/v1/therapist/specialties",
            json={"specialty_ids": [1, 3]},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert sorted([s["id"] for s in data["specialties"]]) == [1, 3]

        stmt = select(TherapistSpecialtyMap).where(
            TherapistSpecialtyMap.therapist_id == therapist_no_uri.id
        )
        mappings = db_session.exec(stmt).all()
        assert sorted([m.specialty_id for m in mappings]) == [1, 3]

    def test_update_specialties_deduplicates_duplicate_specialty_ids(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
    ):
        """Duplicate specialty IDs in request should not create duplicate mappings."""
        response = client.patch(
            "/api/v1/therapist/specialties",
            json={"specialty_ids": [1, 1, 2]},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert sorted([s["id"] for s in data["specialties"]]) == [1, 2]

        stmt = select(TherapistSpecialtyMap).where(
            TherapistSpecialtyMap.therapist_id == therapist_no_uri.id
        )
        mappings = db_session.exec(stmt).all()
        assert sorted([m.specialty_id for m in mappings]) == [1, 2]

    def test_update_specialties_invalid_ids(
        self,
        client,
        therapist_no_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
    ):
        """Fail with invalid specialty IDs."""
        response = client.patch(
            "/api/v1/therapist/specialties",
            json={"specialty_ids": [999]},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400
        assert "Invalid specialty IDs" in response.json()["detail"]

    def test_update_specialties_allows_empty_payload(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
    ):
        db_session.add(
            TherapistSpecialtyMap(
                therapist_id=therapist_no_uri.id,
                specialty_id=sample_specialties_onboarding[0].id,
            )
        )
        db_session.commit()

        response = client.patch(
            "/api/v1/therapist/specialties",
            json={"specialty_ids": [], "new_specialties": []},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        assert response.json()["specialties"] == []

        mappings = db_session.exec(
            select(TherapistSpecialtyMap).where(
                TherapistSpecialtyMap.therapist_id == therapist_no_uri.id
            )
        ).all()
        assert mappings == []


class TestGetTherapistProfile:
    """Tests for GET /therapist/me"""

    def test_get_profile_complete(
        self,
        client,
        db_session: Session,
        therapist_with_uri: Therapist,
        sample_specialties_onboarding: list[TherapistSpecialty],
        mock_jwt_therapist,
    ):
        """Get full therapist profile with all data."""
        # Add event types
        event_type = TherapistEventType(
            therapist_id=therapist_with_uri.id,
            calendly_event_type_uri="https://api.calendly.com/event_types/30MIN",
            duration_minutes=30,
            scheduling_url="https://calendly.com/test/30min",
            is_active=True,
        )
        db_session.add(event_type)

        # Add specialties
        mapping = TherapistSpecialtyMap(
            therapist_id=therapist_with_uri.id,
            specialty_id=sample_specialties_onboarding[0].id,
        )
        db_session.add(mapping)
        db_session.commit()

        response = client.get(
            "/api/v1/therapist/me",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == therapist_with_uri.id
        assert data["display_name"] == "Dr. Test Therapist"
        assert data["license_number"] == "PT-ONBOARD-002"
        assert data["preferred_timezone"] is None
        assert data["email"] == "therapist@test.com"
        assert data["is_active"] is True
        assert data["calendly_user_uri"] == "https://api.calendly.com/users/TEST123"
        assert len(data["specialties"]) == 1
        assert len(data["event_types"]) == 1
        assert data["event_types"][0]["duration_minutes"] == 30
        assert "created_at" in data

    def test_get_profile_minimal(
        self,
        client,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        """Get profile with no event types or specialties."""
        response = client.get(
            "/api/v1/therapist/me",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == therapist_no_uri.id
        assert data["license_number"] == "PT-ONBOARD-001"
        assert data["preferred_timezone"] is None
        assert data["specialties"] == []
        assert data["event_types"] == []
        assert data["calendly_user_uri"] is None


class TestUpdatePreferredTimezone:
    """Tests for PATCH /therapist/me/timezone."""

    def test_update_preferred_timezone_success(
        self,
        client,
        db_session: Session,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        response = client.patch(
            "/api/v1/therapist/me/timezone",
            json={"preferred_timezone": " Asia/Hong_Kong "},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["preferred_timezone"] == "Asia/Hong_Kong"

        db_session.refresh(therapist_no_uri)
        assert therapist_no_uri.preferred_timezone == "Asia/Hong_Kong"

    def test_update_preferred_timezone_rejects_invalid_timezone(
        self,
        client,
        therapist_no_uri: Therapist,
        mock_jwt_therapist,
    ):
        response = client.patch(
            "/api/v1/therapist/me/timezone",
            json={"preferred_timezone": "Mars/Olympus"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "invalid_preferred_timezone"


class TestAuthorization:
    """Tests for JWT authorization and role validation."""

    def test_missing_authorization_header(self, client, therapist_no_uri: Therapist):
        """Fail without Authorization header."""
        response = client.get("/api/v1/therapist/me")
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid_token"

    def test_non_therapist_role(self, client, db_session: Session):
        """Fail if user is not a therapist."""
        # Create non-therapist user
        user = User(
            neon_auth_sub="admin-sub-456",
            email="admin@test.com",
            display_name="Admin User",
            role="admin",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        with patch("app.core.auth._verify_neon_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "admin-sub-456",
                "email": "admin@test.com",
            }

            response = client.get(
                "/api/v1/therapist/me",
                headers={"Authorization": "Bearer test-token"},
            )

            assert response.status_code == 403
            assert response.json()["detail"] == "access_denied"

    def test_unknown_user_returns_access_pending(self, client, db_session: Session):
        """Unknown authenticated user gets pending status and access request row is created."""
        with patch("app.core.auth._verify_neon_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "unknown-sub-789",
                "email": "unknown@test.com",
            }
            response = client.get(
                "/api/v1/therapist/me",
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 403
        assert response.json()["detail"] == "access_pending"

        access_request = db_session.exec(
            select(AccessRequest).where(AccessRequest.neon_auth_sub == "unknown-sub-789")
        ).first()
        assert access_request is not None
        assert access_request.status == "pending"

    def test_rejected_access_request_returns_access_denied(
        self,
        client,
        db_session: Session,
    ):
        """Rejected access requests are denied on protected endpoints."""
        access_request = AccessRequest(
            neon_auth_sub="rejected-sub-789",
            email="rejected@test.com",
            status="rejected",
        )
        db_session.add(access_request)
        db_session.commit()

        with patch("app.core.auth._verify_neon_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "rejected-sub-789",
                "email": "rejected@test.com",
            }
            response = client.get(
                "/api/v1/therapist/me",
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 403
        assert response.json()["detail"] == "access_denied"

    def test_inactive_therapist(self, client, db_session: Session, therapist_user: User):
        """Inactive therapist can access profile endpoint during onboarding."""
        # Create inactive therapist
        therapist = Therapist(
            user_id=therapist_user.id,
            display_name="Dr. Inactive",
            is_active=False,
        )
        db_session.add(therapist)
        db_session.commit()

        with patch("app.core.auth._verify_neon_token") as mock_verify:
            mock_verify.return_value = {
                "sub": therapist_user.neon_auth_sub,
                "email": therapist_user.email,
            }

            response = client.get(
                "/api/v1/therapist/me",
                headers={"Authorization": "Bearer test-token"},
            )

            assert response.status_code == 200
            assert response.json()["is_active"] is False


class TestSlotMappingDurationValidation:
    """Schema validation for bookable slot durations (req 3.2 / platform quick-book).

    30 & 45 required; 60 optional; 15 (and anything else) rejected — 15 is a
    session-plan/billing duration, not a bookable appointment length.
    """

    def _save_request(self, mapping):
        from app.api.v1.schemas.therapist_onboarding import SaveCalendlyRequest

        return SaveCalendlyRequest(calendly_pat="pat-token", slot_mapping=mapping)

    def test_accepts_optional_60_slot(self):
        req = self._save_request(
            {
                "30": "https://calendly.com/t/30",
                "45": "https://calendly.com/t/45",
                "60": "https://calendly.com/t/60",
            }
        )
        assert set(req.slot_mapping.keys()) == {"30", "45", "60"}

    def test_accepts_just_required_30_45(self):
        req = self._save_request(
            {"30": "https://calendly.com/t/30", "45": "https://calendly.com/t/45"}
        )
        assert set(req.slot_mapping.keys()) == {"30", "45"}

    def test_rejects_15_minute_slot(self):
        with pytest.raises(ValueError):
            self._save_request(
                {
                    "15": "https://calendly.com/t/15",
                    "30": "https://calendly.com/t/30",
                    "45": "https://calendly.com/t/45",
                }
            )

    def test_rejects_missing_required_duration(self):
        with pytest.raises(ValueError):
            self._save_request({"30": "https://calendly.com/t/30"})

    def test_update_request_accepts_optional_60(self):
        from app.api.v1.schemas.therapist_onboarding import UpdateSlotMappingRequest

        req = UpdateSlotMappingRequest(
            slot_mapping={
                "30": "https://calendly.com/t/30",
                "45": "https://calendly.com/t/45",
                "60": "https://calendly.com/t/60",
            }
        )
        assert "60" in req.slot_mapping
