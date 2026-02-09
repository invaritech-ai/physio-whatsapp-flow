"""
List all users in your Calendly organization.

Useful for finding therapist User URIs during onboarding.

Usage:
    python scripts/list_organization_users.py
"""

import httpx

from app.core.config import settings


def list_org_users():
    """List all users in the Calendly organization."""
    if not settings.calendly_api_token:
        print("❌ CALENDLY_API_TOKEN not found in .env")
        return

    headers = {
        "Authorization": f"Bearer {settings.calendly_api_token}",
        "Content-Type": "application/json",
    }

    try:
        # Get current user (to get org URI)
        response = httpx.get("https://api.calendly.com/users/me", headers=headers)
        response.raise_for_status()
        org_uri = response.json()["resource"]["current_organization"]

        print("="*60)
        print("Calendly Organization Users")
        print("="*60)

        # List organization memberships
        response = httpx.get(
            "https://api.calendly.com/organization_memberships",
            headers=headers,
            params={"organization": org_uri},
        )
        response.raise_for_status()
        memberships = response.json()["collection"]

        if not memberships:
            print("\n⚠️  No users found in organization")
            return

        print(f"\nFound {len(memberships)} user(s):\n")

        for i, membership in enumerate(memberships, 1):
            user = membership["user"]
            role = membership["role"]

            print(f"{i}. {user['name']}")
            print(f"   Email: {user['email']}")
            print(f"   Role: {role}")
            print(f"   User URI: {user['uri']}")
            print(f"   Scheduling Page: {user['scheduling_url']}")
            print()

        print("="*60)
        print("\n💡 Use the 'User URI' when creating therapist records:")
        print("   POST /admin/therapists")
        print("   { ..., \"calendly_user_uri\": \"https://api.calendly.com/users/XXXXX\" }")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    list_org_users()
