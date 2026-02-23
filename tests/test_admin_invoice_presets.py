"""Tests for admin invoice presets endpoints."""

from datetime import datetime, timezone
from unittest.mock import patch

from sqlmodel import Session

from app.models import User


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _create_admin(db_session: Session) -> User:
    admin = User(
        neon_auth_sub="admin-presets-sub",
        email="admin-presets@test.com",
        display_name="Admin Presets",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def _admin_auth_context(admin: User):
    return patch(
        "app.core.auth._verify_neon_token",
        return_value={
            "sub": admin.neon_auth_sub,
            "email": admin.email,
            "iat": _epoch(datetime.now(timezone.utc)),
        },
    )


def test_create_and_list_invoice_presets(client, db_session: Session):
    admin = _create_admin(db_session)

    with _admin_auth_context(admin):
        response1 = client.post(
            "/api/v1/admin/invoice-presets",
            json={
                "type": "diagnosis",
                "label": "Back Pain",
                "value": "Lower back pain",
                "is_active": True,
                "sort_order": 1,
            },
            headers=_auth_headers(),
        )
    assert response1.status_code == 201
    data1 = response1.json()
    assert data1["type"] == "diagnosis"
    assert data1["label"] == "Back Pain"
    assert data1["value"] == "Lower back pain"

    with _admin_auth_context(admin):
        response2 = client.post(
            "/api/v1/admin/invoice-presets",
            json={
                "type": "special_note",
                "label": "Insurance Note",
                "value": "Please claim from insurance.",
                "is_active": True,
                "sort_order": 2,
            },
            headers=_auth_headers(),
        )
    assert response2.status_code == 201

    with _admin_auth_context(admin):
        list_resp = client.get("/api/v1/admin/invoice-presets", headers=_auth_headers())
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 2

    with _admin_auth_context(admin):
        list_diagnosis = client.get("/api/v1/admin/invoice-presets?type=diagnosis", headers=_auth_headers())
    assert list_diagnosis.status_code == 200
    assert len(list_diagnosis.json()) == 1
    assert list_diagnosis.json()[0]["type"] == "diagnosis"


def test_update_invoice_preset(client, db_session: Session):
    admin = _create_admin(db_session)

    with _admin_auth_context(admin):
        create_resp = client.post(
            "/api/v1/admin/invoice-presets",
            json={
                "type": "special_note",
                "label": "Note 1",
                "value": "Val 1",
                "is_active": True,
                "sort_order": 1,
            },
            headers=_auth_headers(),
        )
    preset_id = create_resp.json()["id"]

    with _admin_auth_context(admin):
        patch_resp = client.patch(
            f"/api/v1/admin/invoice-presets/{preset_id}",
            json={"label": "Updated Note", "is_active": False},
            headers=_auth_headers(),
        )
        
    assert patch_resp.status_code == 200
    patched_data = patch_resp.json()
    assert patched_data["label"] == "Updated Note"
    assert patched_data["is_active"] is False
    assert patched_data["value"] == "Val 1"  # Unchanged
