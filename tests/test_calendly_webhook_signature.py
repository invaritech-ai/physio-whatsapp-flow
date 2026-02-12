"""Unit tests for Calendly webhook signature verification."""

import hashlib
import hmac

from app.api.v1.routes import webhooks


def _build_signature(payload: bytes, secret: str, timestamp: str = "1700000000") -> str:
    signed_payload = f"{timestamp}.{payload.decode()}"
    digest = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return f"{timestamp},{digest}"


def test_verify_calendly_signature_accepts_any_configured_secret(monkeypatch):
    payload = b'{"event":"invitee.created"}'
    signature = _build_signature(payload, "secret-two")

    monkeypatch.setattr(webhooks.settings, "calendly_webhook_secret", "secret-one, secret-two")

    assert webhooks.verify_calendly_signature(payload, signature) is True


def test_verify_calendly_signature_rejects_invalid_signature(monkeypatch):
    payload = b'{"event":"invitee.created"}'
    signature = _build_signature(payload, "wrong-secret")

    monkeypatch.setattr(webhooks.settings, "calendly_webhook_secret", "secret-one, secret-two")

    assert webhooks.verify_calendly_signature(payload, signature) is False
