"""Helper script to generate JSON payloads for frontend UAT."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_session
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, SQLModel
from app.models import BillingPlan, Client, ClientPlanAssignment, PaymentRecord, Receipt, Session as TherapySession, Therapist, User, InvoicePreset

# Use an in-memory SQLite DB for exactly what we need
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SQLModel.metadata.create_all(engine)

def override_get_session():
    with Session(engine) as session:
        yield session

app.dependency_overrides[get_session] = override_get_session

client = TestClient(app)

def seed_db():
    with Session(engine) as session:
        admin = User(
            neon_auth_sub="admin-payloads",
            email="admin@test.com",
            role="admin",
            is_active=True,
            preferred_timezone="America/Los_Angeles",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)

        therapist_user = User(
            neon_auth_sub="therapist-payloads",
            email="therapist@test.com",
            display_name="Dr. Jane Payload",
            role="therapist",
            is_active=True,
        )
        session.add(therapist_user)
        session.commit()
        session.refresh(therapist_user)

        therapist = Therapist(
            user_id=therapist_user.id,
            display_name=therapist_user.display_name,
            license_number="PT-12345",
            is_active=True,
        )
        session.add(therapist)
        
        c1 = Client(phone_e164="+85211112222", name="Patient Alpha", default_receipt_amount_cents=100000)
        session.add(c1)
        session.commit()
        session.refresh(c1)
        session.refresh(therapist)

        plan = BillingPlan(name="Payload Plan", duration_minutes=45, amount_cents=120000, currency="HKD", is_active=True)
        session.add(plan)
        session.commit()
        session.refresh(plan)

        session.add(ClientPlanAssignment(client_id=c1.id, duration_minutes=45, billing_plan_id=plan.id, assigned_by_user_id=admin.id, is_active=True))

        now = datetime.now(timezone.utc)
        s1 = TherapySession(
            client_id=c1.id,
            therapist_id=therapist.id,
            start_time=now - timedelta(days=1),
            end_time=now - timedelta(days=1, minutes=-45),
            duration_minutes=45,
            status="completed",
            source="manual",
        )
        session.add(s1)
        session.commit()
        session.refresh(s1)

        p1 = PaymentRecord(
            client_id=c1.id,
            session_id=s1.id,
            amount_cents=60000,
            currency="HKD",
            source="session_linked",
            payment_method="electronic",
            status="confirmed",
            recorded_by_user_id=admin.id,
            received_by_role="admin",
            paid_at=now - timedelta(hours=10),
        )
        
        p2 = PaymentRecord(
            client_id=c1.id,
            source="admin_manual",
            amount_cents=50000,
            currency="HKD",
            payment_method="cash",
            status="confirmed",
            recorded_by_user_id=admin.id,
            received_by_role="admin",
            paid_at=now - timedelta(hours=2),
        )
        session.add_all([p1, p2])

        preset1 = InvoicePreset(preset_type="diagnosis", label="Shoulder Impingement", value="Subacromial shoulder impingement", is_active=True, sort_order=1)
        preset2 = InvoicePreset(preset_type="special_note", label="Rest Note", value="Recommended 2 days of shoulder rest.", is_active=True, sort_order=1)
        session.add_all([preset1, preset2])

        session.commit()
        return admin.neon_auth_sub, admin.email

def get_auth_headers(admin: User) -> dict[str, str]:
    import time
    import jwt
    from app.core.config import settings
    # We don't actually need a real JWT if we patch the verification, but let's just patch it inline
    pass

def run():
    admin_sub, admin_email = seed_db()
    
    with patch("app.core.auth._verify_neon_token") as mock_verify:
        mock_verify.return_value = {
            "sub": admin_sub,
            "email": admin_email,
            "iat": int(datetime.utcnow().timestamp()),
        }
        headers = {"Authorization": "Bearer test-token"}

        # 1. Billing Queue
        res_queue = client.get("/api/v1/admin/billing/queue?quick_range=7d", headers=headers)
        queue_json = res_queue.json()

        # 2. Presets
        res_presets = client.get("/api/v1/admin/invoice-presets", headers=headers)
        presets_json = res_presets.json()

        # 3. Offline Payment List
        res_payments = client.get(f"/api/v1/admin/clients/1/payments?source=admin_manual", headers=headers)
        payments_json = res_payments.json()

    out_md = f"""# Payload Snapshots for UAT

## `GET /api/v1/admin/billing/queue?quick_range=7d`
```json
{json.dumps(queue_json, indent=2)}
```

## `GET /api/v1/admin/invoice-presets`
```json
{json.dumps(presets_json, indent=2)}
```

## `GET /api/v1/admin/clients/1/payments?source=admin_manual`
```json
{json.dumps(payments_json, indent=2)}
```
"""
    with open("payload_snapshots.md", "w") as f:
        f.write(out_md)
    print("Payloads successfully written to payload_snapshots.md")

if __name__ == "__main__":
    run()
