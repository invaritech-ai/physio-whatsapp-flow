"""Get signing key from existing Calendly webhook."""

import httpx

from app.core.config import settings


def get_webhook_signing_key():
    """Retrieve signing key from existing webhook subscription."""
    if not settings.calendly_api_token:
        print("❌ CALENDLY_API_TOKEN not found in .env")
        return

    headers = {
        "Authorization": f"Bearer {settings.calendly_api_token}",
        "Content-Type": "application/json",
    }

    try:
        # Get organization URI
        response = httpx.get("https://api.calendly.com/users/me", headers=headers)
        response.raise_for_status()
        org_uri = response.json()["resource"]["current_organization"]

        # List webhooks
        response = httpx.get(
            "https://api.calendly.com/webhook_subscriptions",
            headers=headers,
            params={"organization": org_uri, "scope": "organization"},
        )
        response.raise_for_status()
        webhooks = response.json()["collection"]

        if not webhooks:
            print("❌ No webhooks found")
            return

        for webhook in webhooks:
            print(f"\n🔗 Webhook: {webhook['uri']}")
            print(f"   Callback URL: {webhook['callback_url']}")
            print(f"   Events: {', '.join(webhook['events'])}")
            print(f"   State: {webhook['state']}")

            # Get detailed webhook info (signing key is in the detail response)
            webhook_uri = webhook['uri']
            response = httpx.get(webhook_uri, headers=headers)
            response.raise_for_status()
            webhook_detail = response.json()["resource"]

            signing_key = webhook_detail.get("signing_key")
            if signing_key:
                print(f"\n🔑 Signing Key:")
                print(f"   {signing_key}")
                print(f"\n📝 Add to your .env file:")
                print(f"   CALENDLY_WEBHOOK_SECRET={signing_key}")
            else:
                print("\n⚠️  No signing_key found in webhook details")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    get_webhook_signing_key()
