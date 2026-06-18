"""Unit tests for Calendly webhook signature verification."""

import hashlib
import hmac
import json

from unittest.mock import patch

from app.api.v1.routes import webhooks
from app.core.encryption import encrypt_string
from app.models import Therapist, User


def _build_signature(payload: bytes, secret: str, timestamp: str = "1700000000") -> str:
    signed_payload = f"{timestamp}.{payload.decode()}"
    digest = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return f"{timestamp},{digest}"


def _auth_headers(signature: str | None = None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if signature:
        headers["Calendly-Webhook-Signature"] = signature
    return headers


def test_verify_calendly_signature_accepts_any_provided_secret():
    payload = b'{"event":"invitee.created"}'
    signature = _build_signature(payload, "secret-two")

    assert webhooks.verify_calendly_signature(payload, signature, ["secret-one", "secret-two"]) is True


def test_verify_calendly_signature_rejects_invalid_signature():
    payload = b'{"event":"invitee.created"}'
    signature = _build_signature(payload, "wrong-secret")

    assert webhooks.verify_calendly_signature(payload, signature, ["secret-one", "secret-two"]) is False


def test_calendly_webhook_uses_db_stored_signing_key(client, db_session):
    user = User(
        neon_auth_sub="webhook-signature-sub",
        email="webhook-signature@test.com",
        display_name="Dr. Signature",
        role="therapist",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    therapist = Therapist(
        user_id=user.id,
        display_name="Dr. Signature",
        is_active=True,
        calendly_user_uri="https://api.calendly.com/users/SIGNATURE",
        calendly_webhook_signing_key_encrypted=encrypt_string("db-signing-secret"),
    )
    db_session.add(therapist)
    db_session.commit()

    data = {
        "event": "invitee.unknown",
        "payload": {
            "event_memberships": [
                {"user": therapist.calendly_user_uri}
            ]
        },
    }
    payload = json.dumps(data).encode()
    signature = _build_signature(payload, "db-signing-secret")

    response = client.post(
        "/api/v1/webhooks/calendly",
        headers=_auth_headers(signature),
        content=payload,
    )

    assert response.status_code == 200
    body = response.json()
    # Response now also carries a trace_id; assert the meaningful fields.
    assert body["status"] == "ignored"
    assert body["event"] == "invitee.unknown"


def test_calendly_webhook_rejects_when_db_signing_key_missing(client):
    data = {
        "event": "invitee.unknown",
        "payload": {
            "event_memberships": [
                {"user": "https://api.calendly.com/users/UNKNOWN"}
            ]
        },
    }
    payload = json.dumps(data).encode()
    signature = _build_signature(payload, "any-secret")

    with patch.object(webhooks, "_resolve_calendly_signing_secrets", return_value=[]):
        response = client.post(
            "/api/v1/webhooks/calendly",
            headers=_auth_headers(signature),
            content=payload,
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid signature"


