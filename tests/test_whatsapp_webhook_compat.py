"""Compatibility tests for legacy /whatsapp webhook path."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import settings


def test_whatsapp_webhook_sync_mode_alias_and_v1_path(client, monkeypatch):
    # In tests we bypass Twilio signature verification.
    monkeypatch.setattr(settings, "twilio_auth_token", None)
    monkeypatch.setattr(settings, "whatsapp_webhook_sync_enabled", True)

    payload = {
        "From": "whatsapp:+85212345678",
        "Body": "hi",
        "MessageSid": "SM-COMPAT-1",
        "NumMedia": "0",
    }

    with patch(
        "app.api.v1.routes.whatsapp.process_message",
        return_value={"status": "success", "next_state": "ASK_NAME", "client_id": 10},
    ) as mock_process:
        legacy_response = client.post("/whatsapp", data=payload)
        v1_response = client.post("/api/v1/whatsapp", data=payload)

    assert legacy_response.status_code == 200
    assert v1_response.status_code == 200
    assert legacy_response.json()["status"] == "success"
    assert v1_response.json()["status"] == "success"
    assert legacy_response.json()["mode"] == "sync"
    assert v1_response.json()["mode"] == "sync"
    assert mock_process.call_count == 2


def test_whatsapp_webhook_async_mode_alias_and_v1_path(client, monkeypatch):
    # In tests we bypass Twilio signature verification.
    monkeypatch.setattr(settings, "twilio_auth_token", None)
    monkeypatch.setattr(settings, "whatsapp_webhook_sync_enabled", False)
    fake_task = SimpleNamespace(id="task-compat-1")

    payload = {
        "From": "whatsapp:+85212345678",
        "Body": "hi",
        "MessageSid": "SM-COMPAT-2",
        "NumMedia": "0",
    }

    with patch(
        "app.api.v1.routes.whatsapp.process_whatsapp_message.delay",
        return_value=fake_task,
    ) as mock_delay:
        legacy_response = client.post("/whatsapp", data=payload)
        v1_response = client.post("/api/v1/whatsapp", data=payload)

    assert legacy_response.status_code == 200
    assert v1_response.status_code == 200
    assert legacy_response.json()["status"] == "queued"
    assert v1_response.json()["status"] == "queued"
    assert legacy_response.json()["mode"] == "async"
    assert v1_response.json()["mode"] == "async"
    assert mock_delay.call_count == 2
