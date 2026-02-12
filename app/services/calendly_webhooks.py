"""Calendly webhook registration helpers for therapist self-service flows."""

from __future__ import annotations

import json
from typing import Any

import requests


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


def check_webhook_registration(calendly_pat: str, callback_url: str) -> dict[str, Any]:
    """
    Inspect webhook subscriptions relevant to the therapist's Calendly account.

    Returns a summary indicating whether a matching active webhook exists for this
    backend callback URL and required event set.
    """
    user_uri, organization_uri = get_user_context(calendly_pat)
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

    subscriptions = _summarize_subscriptions([*user_subs, *org_subs])

    matching = [
        sub for sub in subscriptions if _normalize_url(sub["callback_url"]) == normalized_callback
    ]

    covered_events: set[str] = set()
    has_matching_active = False
    for sub in matching:
        covered_events.update(sub.get("events", []))
        if sub.get("state") == "active" and REQUIRED_EVENTS.issubset(set(sub.get("events", []))):
            has_matching_active = True

    missing_events = sorted(REQUIRED_EVENTS - covered_events)

    return {
        "user_uri": user_uri,
        "organization_uri": organization_uri,
        "has_matching_webhook": has_matching_active,
        "needs_registration": not has_matching_active,
        "missing_events": missing_events,
        "subscriptions": subscriptions,
        "warnings": warnings,
    }


def register_webhook_if_needed(calendly_pat: str, callback_url: str) -> dict[str, Any]:
    """
    Ensure a webhook exists for this therapist account and callback URL.

    Uses user-scope registration to support therapists across different orgs.
    """
    status = check_webhook_registration(calendly_pat, callback_url)
    if status["has_matching_webhook"]:
        return {
            **status,
            "created": False,
            "created_webhook_uri": None,
            "signing_key": None,
        }

    payload = {
        "url": callback_url,
        "events": sorted(REQUIRED_EVENTS),
        "organization": status["organization_uri"],
        "scope": "user",
        "user": status["user_uri"],
    }

    try:
        response = requests.post(
            f"{BASE_URL}/webhook_subscriptions",
            headers=_headers(calendly_pat),
            json=payload,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise CalendlyWebhookError(f"Failed to register Calendly webhook: {exc}") from exc

    if response.status_code not in (200, 201):
        # A concurrent registration may have already succeeded. Re-check before failing.
        refreshed = check_webhook_registration(calendly_pat, callback_url)
        if refreshed["has_matching_webhook"]:
            return {
                **refreshed,
                "created": False,
                "created_webhook_uri": None,
                "signing_key": None,
            }
        raise CalendlyWebhookError(f"Failed to register Calendly webhook: {_parse_error(response)}")

    resource = response.json().get("resource", {})
    refreshed = check_webhook_registration(calendly_pat, callback_url)
    return {
        **refreshed,
        "created": True,
        "created_webhook_uri": resource.get("uri"),
        "signing_key": resource.get("signing_key"),
    }
