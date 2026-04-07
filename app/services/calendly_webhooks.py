"""Calendly webhook registration helpers for therapist self-service flows."""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.calendly.com"
# Calendly webhook subscriptions accept invitee.created/invitee.canceled.
# Reschedules are inferred from those payloads (old/new linkage).
REQUIRED_EVENTS = {"invitee.created", "invitee.canceled"}


class CalendlyWebhookError(Exception):
    """Raised when Calendly webhook operations fail."""


def _headers(calendly_pat: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {calendly_pat}",
        "Content-Type": "application/json",
    }


def _generate_signing_key() -> str:
    """Generate a strong webhook signing key for Calendly create-subscription API."""
    return secrets.token_urlsafe(48)


def _normalize_url(url: str) -> str:
    return url.rstrip("/")


def _parse_error(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            title = payload.get("title")
            message = payload.get("message")
            if title and message:
                return f"{title}: {message}"
            if message:
                return str(message)
            if title:
                return str(title)
            return json.dumps(payload)
    except Exception:
        pass
    return response.text or f"HTTP {response.status_code}"


def get_user_context(calendly_pat: str) -> tuple[str, str]:
    """Return (user_uri, organization_uri) from Calendly /users/me."""
    try:
        response = requests.get(
            f"{BASE_URL}/users/me",
            headers=_headers(calendly_pat),
            timeout=20,
        )
    except requests.RequestException as exc:
        raise CalendlyWebhookError(f"Failed to fetch Calendly user info: {exc}") from exc

    if response.status_code != 200:
        raise CalendlyWebhookError(f"Failed to fetch Calendly user info: {_parse_error(response)}")

    resource = response.json().get("resource", {})
    user_uri = resource.get("uri")
    organization_uri = resource.get("current_organization")
    if not user_uri or not organization_uri:
        raise CalendlyWebhookError("Calendly user context is missing required URIs")

    return user_uri, organization_uri


def _list_scope_subscriptions(
    calendly_pat: str,
    organization_uri: str,
    scope: str,
    user_uri: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    params: dict[str, str] = {
        "organization": organization_uri,
        "scope": scope,
    }
    if user_uri:
        params["user"] = user_uri

    try:
        response = requests.get(
            f"{BASE_URL}/webhook_subscriptions",
            headers=_headers(calendly_pat),
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise CalendlyWebhookError(
            f"Failed to list Calendly webhooks for scope '{scope}': {exc}"
        ) from exc

    if response.status_code == 200:
        return response.json().get("collection", []), None

    # Some accounts/plans may reject one scope; treat as a non-fatal warning.
    if response.status_code in (400, 403, 404):
        return [], f"{scope}_scope_list_failed: {_parse_error(response)}"

    raise CalendlyWebhookError(
        f"Failed to list Calendly webhooks for scope '{scope}': {_parse_error(response)}"
    )


def _summarize_subscriptions(subscriptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_uris: set[str] = set()
    summarized: list[dict[str, Any]] = []

    for sub in subscriptions:
        uri = sub.get("uri")
        if uri and uri in seen_uris:
            continue
        if uri:
            seen_uris.add(uri)

        summarized.append(
            {
                "uri": uri,
                "scope": sub.get("scope"),
                "state": sub.get("state"),
                "callback_url": sub.get("callback_url", ""),
                "events": sorted(sub.get("events", [])),
            }
        )

    return summarized


def _delete_subscription(calendly_pat: str, subscription_uri: str) -> None:
    """Delete an existing Calendly webhook subscription by full URI."""
    try:
        response = requests.delete(
            subscription_uri,
            headers=_headers(calendly_pat),
            timeout=20,
        )
    except requests.RequestException as exc:
        raise CalendlyWebhookError(f"Failed to delete Calendly webhook subscription: {exc}") from exc

    if response.status_code not in (200, 202, 204):
        raise CalendlyWebhookError(
            f"Failed to delete Calendly webhook subscription: {_parse_error(response)}"
        )


def _matching_subscription_uris(
    calendly_pat: str,
    callback_url: str,
    *,
    organization_uri: str,
    user_uri: str,
) -> list[str]:
    """List user-scope webhook URIs matching this callback URL."""
    normalized_callback = _normalize_url(callback_url)
    user_subs, _ = _list_scope_subscriptions(
        calendly_pat,
        organization_uri,
        scope="user",
        user_uri=user_uri,
    )
    uris: list[str] = []
    for sub in user_subs:
        sub_uri = sub.get("uri")
        callback = sub.get("callback_url")
        if not isinstance(sub_uri, str) or not isinstance(callback, str):
            continue
        if _normalize_url(callback) == normalized_callback:
            uris.append(sub_uri)
    return uris


def check_webhook_registration(calendly_pat: str, callback_url: str) -> dict[str, Any]:
    """
    Inspect webhook subscriptions relevant to the therapist's Calendly account.

    Returns a summary indicating whether a matching active webhook exists for this
    backend callback URL and required event set.
    """
    logger.debug("[DEBUG-REG] check_webhook_registration called, callback_url=%s", callback_url)
    user_uri, organization_uri = get_user_context(calendly_pat)
    logger.debug("[DEBUG-REG] user_uri=%s, org_uri=%s", user_uri, organization_uri)
    normalized_callback = _normalize_url(callback_url)

    warnings: list[str] = []
    user_subs, user_warning = _list_scope_subscriptions(
        calendly_pat,
        organization_uri,
        scope="user",
        user_uri=user_uri,
    )
    if user_warning:
        warnings.append(user_warning)

    org_subs, org_warning = _list_scope_subscriptions(
        calendly_pat,
        organization_uri,
        scope="organization",
    )
    if org_warning:
        warnings.append(org_warning)

    logger.debug("[DEBUG-REG] user_subs=%d, org_subs=%d", len(user_subs), len(org_subs))

    subscriptions = _summarize_subscriptions([*user_subs, *org_subs])
    logger.debug("[DEBUG-REG] all subscriptions: %s", subscriptions)

    matching = [
        sub for sub in subscriptions if _normalize_url(sub["callback_url"]) == normalized_callback
    ]
    logger.debug("[DEBUG-REG] matching subscriptions (url=%s): %s", normalized_callback, matching)

    covered_events: set[str] = set()
    has_matching_active = False
    for sub in matching:
        covered_events.update(sub.get("events", []))
        if sub.get("state") == "active" and REQUIRED_EVENTS.issubset(set(sub.get("events", []))):
            has_matching_active = True

    missing_events = sorted(REQUIRED_EVENTS - covered_events)
    logger.debug(
        "[DEBUG-REG] has_matching_active=%s, covered_events=%s, missing=%s",
        has_matching_active, covered_events, missing_events,
    )

    return {
        "user_uri": user_uri,
        "organization_uri": organization_uri,
        "has_matching_webhook": has_matching_active,
        "needs_registration": not has_matching_active,
        "missing_events": missing_events,
        "subscriptions": subscriptions,
        "warnings": warnings,
    }


def register_webhook_if_needed(
    calendly_pat: str,
    callback_url: str,
    *,
    force_recreate: bool = False,
) -> dict[str, Any]:
    """
    Ensure a webhook exists for this therapist account and callback URL.

    Uses user-scope registration to support therapists across different orgs.
    """
    logger.debug("[DEBUG-REG] register_webhook_if_needed called, callback_url=%s", callback_url)
    status = check_webhook_registration(calendly_pat, callback_url)
    if status["has_matching_webhook"] and not force_recreate:
        logger.debug("[DEBUG-REG] webhook already exists, skipping creation (signing_key will be None)")
        return {
            **status,
            "created": False,
            "created_webhook_uri": None,
            "signing_key": None,
        }

    if status["has_matching_webhook"] and force_recreate:
        logger.debug("[DEBUG-REG] force_recreate enabled; deleting existing matching webhook(s)")
        matching_uris = _matching_subscription_uris(
            calendly_pat,
            callback_url,
            organization_uri=status["organization_uri"],
            user_uri=status["user_uri"],
        )
        for uri in matching_uris:
            _delete_subscription(calendly_pat, uri)
        status = check_webhook_registration(calendly_pat, callback_url)
        if status["has_matching_webhook"]:
            raise CalendlyWebhookError(
                "Unable to recreate webhook: matching subscription still exists after delete attempt."
            )

    generated_signing_key = _generate_signing_key()
    logger.debug("[DEBUG-REG] generating new signing key: %s…", generated_signing_key[:8])
    payload = {
        "url": callback_url,
        "events": sorted(REQUIRED_EVENTS),
        "organization": status["organization_uri"],
        "scope": "user",
        "user": status["user_uri"],
        # Per Calendly create-subscription contract, provide signing_key explicitly.
        "signing_key": generated_signing_key,
    }
    logger.debug("[DEBUG-REG] creating webhook with payload: %s", {k: v for k, v in payload.items() if k != "signing_key"})

    try:
        response = requests.post(
            f"{BASE_URL}/webhook_subscriptions",
            headers=_headers(calendly_pat),
            json=payload,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise CalendlyWebhookError(f"Failed to register Calendly webhook: {exc}") from exc

    response_preview = str(getattr(response, "text", "") or "")[:500]
    logger.debug(
        "[DEBUG-REG] Calendly create response: status=%d, body=%s",
        response.status_code,
        response_preview,
    )

    if response.status_code not in (200, 201):
        # A concurrent registration may have already succeeded. Re-check before failing.
        refreshed = check_webhook_registration(calendly_pat, callback_url)
        if refreshed["has_matching_webhook"]:
            logger.debug("[DEBUG-REG] concurrent registration detected, returning existing (no signing_key)")
            return {
                **refreshed,
                "created": False,
                "created_webhook_uri": None,
                "signing_key": None,
            }
        raise CalendlyWebhookError(f"Failed to register Calendly webhook: {_parse_error(response)}")

    resource = response.json().get("resource", {})
    logger.debug("[DEBUG-REG] webhook created successfully, uri=%s", resource.get("uri"))
    refreshed = check_webhook_registration(calendly_pat, callback_url)
    return {
        **refreshed,
        "created": True,
        "created_webhook_uri": resource.get("uri"),
        # Persist the deterministic key we sent in create payload.
        "signing_key": generated_signing_key,
    }
