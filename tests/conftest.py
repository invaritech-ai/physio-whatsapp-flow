"""Shared test fixtures for pytest."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.db.session import get_session
from app.main import app
from app.models import (
    Client,
    Session as TherapySession,
    Therapist,
    TherapistEventType,
    TherapistSpecialty,
    User,
)


@pytest.fixture(name="db_session")
def db_session_fixture():
    """Create in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


@pytest.fixture(name="mock_send_whatsapp")
def mock_send_whatsapp_fixture():
    """Mock send_whatsapp_message to prevent actual Twilio calls."""
    # Patch where it's used (in helpers), not where it's defined
    import uuid

    with patch("app.services.bot.helpers.send_whatsapp_message") as mock:
        # Return unique SID each time to avoid unique constraint violations
        mock.side_effect = lambda *args, **kwargs: f"SM{uuid.uuid4().hex[:10]}"
        yield mock


@pytest.fixture(name="sample_client")
def sample_client_fixture(db_session):
    """Create a sample client for testing."""
    client = Client(
        phone_e164="+85212345678", name="Test User", conversation_state="IDLE"
    )
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)
    return client


@pytest.fixture(name="sample_specialties")
def sample_specialties_fixture(db_session):
    """Create sample specialties for testing."""
    specialties = [
        TherapistSpecialty(name="Sports Rehab", is_active=True),
        TherapistSpecialty(name="Orthopedic", is_active=True),
        TherapistSpecialty(name="Neurological", is_active=True),
    ]
    for spec in specialties:
        db_session.add(spec)
    db_session.commit()
    for spec in specialties:
        db_session.refresh(spec)
    return specialties


@pytest.fixture(name="sample_therapist")
def sample_therapist_fixture(db_session):
    """Create a sample therapist for testing."""
    # First create user
    user = User(
        neon_auth_sub="test-auth-sub",
        email="therapist@test.com",
        display_name="Dr. Test",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    if user.id is not None:
        # Then create therapist
        therapist = Therapist(
            user_id=user.id, display_name="Dr. Test Therapist", is_active=True
        )
        db_session.add(therapist)
        db_session.commit()
        db_session.refresh(therapist)

        # Seed standard event types so booking-link flows work in bot tests.
        event_types = [
            TherapistEventType(
                therapist_id=therapist.id,
                calendly_event_type_uri=f"https://api.calendly.com/event_types/{therapist.id}-30",
                duration_minutes=30,
                scheduling_url="https://calendly.com/test-therapist/30min",
                is_active=True,
            ),
            TherapistEventType(
                therapist_id=therapist.id,
                calendly_event_type_uri=f"https://api.calendly.com/event_types/{therapist.id}-45",
                duration_minutes=45,
                scheduling_url="https://calendly.com/test-therapist/45min",
                is_active=True,
            ),
            TherapistEventType(
                therapist_id=therapist.id,
                calendly_event_type_uri=f"https://api.calendly.com/event_types/{therapist.id}-60",
                duration_minutes=60,
                scheduling_url="https://calendly.com/test-therapist/60min",
                is_active=True,
            ),
        ]
        db_session.add_all(event_types)
        db_session.commit()
        return therapist


@pytest.fixture(name="client")
def client_fixture(db_session):
    """Create a TestClient with overridden database dependency."""

    def get_session_override():
        return db_session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_s3_invoice_storage(request):
    """Mock S3 upload in tests to avoid real network calls.

    Tests that exercise the real S3 upload logic can disable this with
    ``@pytest.mark.no_s3_mock``.
    """
    if "no_s3_mock" in {m.name for m in request.node.iter_markers()}:
        yield
        return
    with patch(
        "app.services.invoice_storage._upload_to_s3",
        side_effect=lambda *, invoice_id, local_pdf_path: f"https://test-bucket.s3.example.com/invoices/invoice-{invoice_id}.pdf",
    ):
        yield


@pytest.fixture(autouse=True)
def mock_invoice_whatsapp():
    """Mock WhatsApp sends triggered by invoice generation to prevent real Twilio calls."""
    with patch(
        "app.services.invoice_whatsapp.send_whatsapp_message",
        return_value="test-whatsapp-sid",
    ):
        yield
