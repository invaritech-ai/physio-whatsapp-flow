"""Unit tests for Calendly webhook registration service behavior."""

from unittest.mock import Mock, patch

from app.services.calendly_webhooks import register_webhook_if_needed


def test_register_webhook_sends_generated_signing_key_and_returns_it():
    callback_url = "https://api.test.local/api/v1/webhooks/calendly"
    initial_status = {
        "user_uri": "https://api.calendly.com/users/U1",
        "organization_uri": "https://api.calendly.com/organizations/O1",
        "has_matching_webhook": False,
        "needs_registration": True,
        "missing_events": ["invitee.canceled", "invitee.created"],
        "subscriptions": [],
        "warnings": [],
    }
    refreshed_status = {
        "user_uri": "https://api.calendly.com/users/U1",
        "organization_uri": "https://api.calendly.com/organizations/O1",
        "has_matching_webhook": True,
        "needs_registration": False,
        "missing_events": [],
        "subscriptions": [],
        "warnings": [],
    }

    post_response = Mock()
    post_response.status_code = 201
    post_response.json.return_value = {
        "resource": {
            "uri": "https://api.calendly.com/webhook_subscriptions/SUB1",
            # Service should use the key sent in payload, regardless of response echo.
            "signing_key": None,
        }
    }

    with (
        patch(
            "app.services.calendly_webhooks.check_webhook_registration",
            side_effect=[initial_status, refreshed_status],
        ) as mock_check,
        patch(
            "app.services.calendly_webhooks._generate_signing_key",
            return_value="generated-signing-key",
        ),
        patch("app.services.calendly_webhooks.requests.post", return_value=post_response) as mock_post,
    ):
        result = register_webhook_if_needed("test_pat", callback_url)

    assert result["created"] is True
    assert result["created_webhook_uri"] == "https://api.calendly.com/webhook_subscriptions/SUB1"
    assert result["signing_key"] == "generated-signing-key"

    post_payload = mock_post.call_args.kwargs["json"]
    assert post_payload["signing_key"] == "generated-signing-key"
    assert post_payload["url"] == callback_url
    assert set(post_payload["events"]) == {"invitee.created", "invitee.canceled"}
    assert mock_check.call_count == 2


def test_register_webhook_skips_create_when_matching_exists():
    callback_url = "https://api.test.local/api/v1/webhooks/calendly"
    status = {
        "user_uri": "https://api.calendly.com/users/U1",
        "organization_uri": "https://api.calendly.com/organizations/O1",
        "has_matching_webhook": True,
        "needs_registration": False,
        "missing_events": [],
        "subscriptions": [],
        "warnings": [],
    }

    with (
        patch("app.services.calendly_webhooks.check_webhook_registration", return_value=status),
        patch("app.services.calendly_webhooks.requests.post") as mock_post,
    ):
        result = register_webhook_if_needed("test_pat", callback_url)

    assert result["created"] is False
    assert result["created_webhook_uri"] is None
    assert result["signing_key"] is None
    mock_post.assert_not_called()
