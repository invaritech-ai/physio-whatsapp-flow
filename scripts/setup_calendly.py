"""
Calendly setup script - one-time configuration.

This script:
1. Tests your Calendly API token
2. Gets your user URI
3. Lists your event types
4. Registers webhook subscription (if webhook URL provided)
5. Outputs setup data for .env and database

Usage:
    python scripts/setup_calendly.py
    python scripts/setup_calendly.py --webhook-url https://your-domain.com/api/v1/webhooks/calendly
"""

import argparse
import json
import sys
from datetime import datetime

import httpx

from app.core.config import settings


def test_token():
    """Step 1: Test API token and get user info."""
    print("\n=== Step 1: Testing Calendly API Token ===")

    if not settings.calendly_api_token:
        print("❌ CALENDLY_API_TOKEN not found in .env")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {settings.calendly_api_token}",
        "Content-Type": "application/json",
    }

    try:
        response = httpx.get("https://api.calendly.com/users/me", headers=headers)
        response.raise_for_status()
        data = response.json()

        user = data["resource"]
        print(f"✅ Token valid!")
        print(f"   Name: {user['name']}")
        print(f"   Email: {user['email']}")
        print(f"   User URI: {user['uri']}")

        return user["uri"], headers

    except httpx.HTTPStatusError as e:
        print(f"❌ API Error: {e.response.status_code} - {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


def list_event_types(user_uri, headers):
    """Step 2: List all event types for the user."""
    print("\n=== Step 2: Fetching Event Types ===")

    try:
        response = httpx.get(
            "https://api.calendly.com/event_types",
            headers=headers,
            params={"user": user_uri, "active": "true"},
        )
        response.raise_for_status()
        data = response.json()

        event_types = data["collection"]

        if not event_types:
            print("⚠️  No event types found. Please create event types in Calendly first.")
            print("   Required: 30-minute, 45-minute, and 60-minute event types")
            return []

        print(f"✅ Found {len(event_types)} event type(s):")

        results = []
        for et in event_types:
            duration = et["duration"]
            print(f"\n   📅 {et['name']}")
            print(f"      Duration: {duration} minutes")
            print(f"      URI: {et['uri']}")
            print(f"      Scheduling URL: {et['scheduling_url']}")
            print(f"      Active: {et['active']}")

            results.append({
                "name": et["name"],
                "duration_minutes": duration,
                "calendly_event_type_uri": et["uri"],
                "scheduling_url": et["scheduling_url"],
                "is_active": et["active"],
            })

        return results

    except Exception as e:
        print(f"❌ Error fetching event types: {e}")
        return []


def list_existing_webhooks(headers):
    """Step 3: List existing webhook subscriptions."""
    print("\n=== Step 3: Checking Existing Webhooks ===")

    try:
        # Get organization URI first
        response = httpx.get("https://api.calendly.com/users/me", headers=headers)
        response.raise_for_status()
        org_uri = response.json()["resource"]["current_organization"]

        # List webhooks for organization
        response = httpx.get(
            "https://api.calendly.com/webhook_subscriptions",
            headers=headers,
            params={"organization": org_uri, "scope": "organization"},
        )
        response.raise_for_status()
        data = response.json()

        webhooks = data["collection"]

        if not webhooks:
            print("   No existing webhooks found")
            return None, org_uri

        print(f"   Found {len(webhooks)} existing webhook(s):")
        for wh in webhooks:
            print(f"\n   🔗 {wh['uri']}")
            print(f"      Callback URL: {wh['callback_url']}")
            print(f"      Events: {', '.join(wh['events'])}")
            print(f"      State: {wh['state']}")
            print(f"      Created: {wh['created_at']}")

        return webhooks, org_uri

    except Exception as e:
        print(f"⚠️  Could not fetch webhooks: {e}")
        return None, None


def create_webhook(webhook_url, headers, org_uri):
    """Step 4: Create webhook subscription."""
    print(f"\n=== Step 4: Creating Webhook Subscription ===")
    print(f"   Webhook URL: {webhook_url}")

    # Events we want to subscribe to
    events = [
        "invitee.created",
        "invitee.rescheduled",
        "invitee.canceled",
    ]

    payload = {
        "url": webhook_url,
        "events": events,
        "organization": org_uri,
        "scope": "organization",
    }

    try:
        response = httpx.post(
            "https://api.calendly.com/webhook_subscriptions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        webhook = data["resource"]
        signing_key = webhook.get("signing_key")

        print(f"✅ Webhook created successfully!")
        print(f"   URI: {webhook['uri']}")
        print(f"   State: {webhook['state']}")
        print(f"   Events: {', '.join(webhook['events'])}")

        if signing_key:
            print(f"\n🔑 IMPORTANT: Save this signing key to your .env file:")
            print(f"   CALENDLY_WEBHOOK_SECRET={signing_key}")
        else:
            print(f"\n⚠️  No signing_key in response. Full webhook data:")
            print(f"   {json.dumps(webhook, indent=2)}")

        return signing_key

    except httpx.HTTPStatusError as e:
        error_data = e.response.json()
        print(f"❌ Failed to create webhook: {e.response.status_code}")
        print(f"   Error: {error_data}")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def print_summary(user_uri, event_types, signing_key=None):
    """Print setup summary with next steps."""
    print("\n" + "="*60)
    print("=== Setup Summary ===")
    print("="*60)

    print(f"\n1️⃣  Your Calendly User URI:")
    print(f"   {user_uri}")

    print(f"\n2️⃣  Event Types Found: {len(event_types)}")
    if event_types:
        for et in event_types:
            print(f"   • {et['duration_minutes']} min - {et['scheduling_url']}")

    if signing_key:
        print(f"\n3️⃣  Webhook Signing Key (add to .env):")
        print(f"   CALENDLY_WEBHOOK_SECRET={signing_key}")

    print("\n" + "="*60)
    print("=== Next Steps ===")
    print("="*60)

    print("\n1. Create a therapist record for yourself:")
    print("""
   POST /admin/therapists
   {
     "neon_auth_sub": "your-neon-auth-id",
     "email": "your@email.com",
     "display_name": "Dr. Your Name",
     "calendly_user_uri": "%s"
   }
   """ % user_uri)

    if event_types:
        print("\n2. Run event type sync script (coming next) to populate TherapistEventType table")
    else:
        print("\n2. Create event types in Calendly:")
        print("   - Go to https://calendly.com/event_types")
        print("   - Create: 30-min, 45-min, 60-min session types")
        print("   - Run this script again to sync")

    print("\n3. Test the bot flow with real Calendly links")


def main():
    parser = argparse.ArgumentParser(description="Setup Calendly integration")
    parser.add_argument(
        "--webhook-url",
        help="Your public webhook URL (e.g., https://yourdomain.com/api/v1/webhooks/calendly)",
    )
    args = parser.parse_args()

    print("="*60)
    print("Calendly Setup Script")
    print("="*60)

    # Step 1: Test token and get user URI
    user_uri, headers = test_token()

    # Step 2: List event types
    event_types = list_event_types(user_uri, headers)

    # Step 3: Check existing webhooks
    existing_webhooks, org_uri = list_existing_webhooks(headers)

    # Step 4: Create webhook if URL provided
    signing_key = None
    if args.webhook_url:
        if existing_webhooks:
            print("\n⚠️  Webhooks already exist. Skipping creation.")
            print("   Delete existing webhooks first if you want to recreate.")
        elif org_uri:
            signing_key = create_webhook(args.webhook_url, headers, org_uri)
    else:
        print("\n💡 Tip: Run with --webhook-url to create webhook subscription")
        print("   Example: python scripts/setup_calendly.py --webhook-url https://yourdomain.com/api/v1/webhooks/calendly")

    # Print summary
    print_summary(user_uri, event_types, signing_key)


if __name__ == "__main__":
    main()
