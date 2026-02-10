import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from app.core.config import settings

CALENDLY_API_TOKEN = settings.calendly_api_token or os.getenv("CALENDLY_API_TOKEN")
BASE_URL = "https://api.calendly.com"

headers = {
    "Authorization": f"Bearer {CALENDLY_API_TOKEN}",
    "Content-Type": "application/json",
}


def get_current_user_uuid():
    """Fetch the current user's URI/UUID from Calendly."""
    url = f"{BASE_URL}/users/me"
    response = requests.get(url, headers=headers, timeout=20)
    if response.status_code == 200:
        return response.json()["resource"]["uri"]
    return None


def get_event_types(user_uri):
    """Fetch event types for the user."""
    url = f"{BASE_URL}/event_types?user={user_uri}"
    response = requests.get(url, headers=headers, timeout=20)
    return response.json().get("collection", [])


def check_availability(duration_minutes: int, start_date: datetime = None, end_date: datetime = None):
    """
    Check for available slots by fetching scheduled events and finding gaps.
    Assumes a 9am-5pm work day.
    """
    if not start_date:
        now = datetime.now(timezone.utc)
        start_date = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now.hour >= 17:
            start_date += timedelta(days=1)

    if not end_date:
        end_date = start_date + timedelta(days=3)

    user_uri = get_current_user_uuid()
    if not user_uri:
        print("Error: Could not fetch user URI")
        return []

    url = f"{BASE_URL}/scheduled_events"
    params = {
        "user": user_uri,
        "min_start_time": start_date.isoformat(),
        "max_start_time": end_date.isoformat(),
        "status": "active",
    }
    response = requests.get(url, headers=headers, params=params, timeout=30)
    scheduled_events = response.json().get("collection", [])

    scheduled_events.sort(key=lambda x: x["start_time"])

    available_slots = []
    current_day = start_date
    while current_day < end_date:
        work_start = current_day.replace(hour=9, minute=0, second=0)
        work_end = current_day.replace(hour=17, minute=0, second=0)

        day_events = [e for e in scheduled_events if e["start_time"].startswith(current_day.strftime("%Y-%m-%d"))]

        last_end_time = work_start
        for event in day_events:
            evt_start = datetime.fromisoformat(event["start_time"].replace("Z", "+00:00"))
            evt_end = datetime.fromisoformat(event["end_time"].replace("Z", "+00:00"))

            if (evt_start - last_end_time).total_seconds() / 60 >= duration_minutes:
                available_slots.append(last_end_time)

            last_end_time = max(last_end_time, evt_end)

        if (work_end - last_end_time).total_seconds() / 60 >= duration_minutes:
            available_slots.append(last_end_time)

        current_day += timedelta(days=1)

    return available_slots


def get_event_link(duration_minutes: int):
    """Fetch the Scheduling URL for the event type matching the duration."""
    user_uri = get_current_user_uuid()
    if not user_uri:
        return None

    event_types = get_event_types(user_uri)

    target_event = None
    for et in event_types:
        if not et.get("active"):
            continue
        if str(duration_minutes) in et.get("name", ""):
            target_event = et
            break

    if not target_event:
        target_event = next((et for et in event_types if et.get("active")), None)

    if target_event:
        return target_event.get("scheduling_url")

    return "https://calendly.com"


# PAT-parameterized functions for therapist self-service onboarding


def get_user_info_with_pat(calendly_pat: str) -> dict[str, Any] | None:
    """Fetch Calendly user info using provided Personal Access Token.

    Args:
        calendly_pat: Therapist's Calendly Personal Access Token

    Returns:
        Dictionary with user info (uri, name, email) or None if request fails
    """
    url = f"{BASE_URL}/users/me"
    pat_headers = {
        "Authorization": f"Bearer {calendly_pat}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=pat_headers, timeout=20)
        if response.status_code == 200:
            resource = response.json()["resource"]
            return {
                "uri": resource["uri"],
                "name": resource.get("name", ""),
                "email": resource.get("email", ""),
            }
    except Exception:
        pass

    return None


def get_scheduled_event_with_pat(
    event_uri: str, calendly_pat: str
) -> dict[str, Any] | None:
    """Fetch full scheduled event details using provided Personal Access Token.

    Args:
        event_uri: Full Calendly scheduled event URI
                   (e.g., "https://api.calendly.com/scheduled_events/XXXXX")
        calendly_pat: Therapist's Calendly Personal Access Token

    Returns:
        Dictionary with start_time, end_time, event_type (URI), status — or None on failure
    """
    pat_headers = {
        "Authorization": f"Bearer {calendly_pat}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(event_uri, headers=pat_headers, timeout=20)
        if response.status_code == 200:
            resource = response.json()["resource"]
            return {
                "start_time": resource["start_time"],
                "end_time": resource["end_time"],
                "event_type": resource["event_type"],
                "status": resource.get("status", "active"),
            }
    except Exception:
        pass

    return None


def get_event_types_with_pat(user_uri: str, calendly_pat: str) -> list[dict[str, Any]]:
    """Fetch event types using provided Personal Access Token.

    Args:
        user_uri: Calendly user URI (e.g., "https://api.calendly.com/users/XXXXX")
        calendly_pat: Therapist's Calendly Personal Access Token

    Returns:
        List of event type dictionaries from Calendly API
    """
    url = f"{BASE_URL}/event_types?user={user_uri}&active=true"
    pat_headers = {
        "Authorization": f"Bearer {calendly_pat}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=pat_headers, timeout=20)
        if response.status_code == 200:
            return response.json().get("collection", [])
    except Exception:
        pass

    return []
