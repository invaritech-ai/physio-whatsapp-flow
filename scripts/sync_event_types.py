"""
Sync Calendly event types for therapists.

Fetches event types from Calendly API and creates/updates TherapistEventType records.

Usage:
    python scripts/sync_event_types.py --therapist-id 2
    python scripts/sync_event_types.py --all
"""

import argparse
import sys

import httpx
from sqlmodel import Session, select

from app.core.config import settings
from app.db.session import engine
from app.models import Therapist, TherapistEventType


def get_calendly_headers():
    """Get headers for Calendly API requests."""
    if not settings.calendly_api_token:
        print("❌ CALENDLY_API_TOKEN not found in .env")
        sys.exit(1)

    return {
        "Authorization": f"Bearer {settings.calendly_api_token}",
        "Content-Type": "application/json",
    }


def fetch_event_types(calendly_user_uri):
    """Fetch event types for a Calendly user."""
    headers = get_calendly_headers()

    try:
        response = httpx.get(
            "https://api.calendly.com/event_types",
            headers=headers,
            params={"user": calendly_user_uri, "active": "true"},
        )
        response.raise_for_status()
        data = response.json()
        return data["collection"]

    except Exception as e:
        print(f"❌ Error fetching event types: {e}")
        return []


def sync_therapist_event_types(db: Session, therapist: Therapist):
    """Sync event types for a single therapist."""
    print(f"\n📋 Syncing event types for {therapist.display_name} (ID: {therapist.id})")

    if not therapist.calendly_user_uri:
        print(f"   ⚠️  No Calendly user URI set. Skipping.")
        return 0

    # Fetch event types from Calendly
    event_types = fetch_event_types(therapist.calendly_user_uri)

    if not event_types:
        print(f"   ⚠️  No active event types found in Calendly")
        return 0

    print(f"   ✅ Found {len(event_types)} event type(s) in Calendly:")

    synced = 0
    for et in event_types:
        duration = et["duration"]
        name = et["name"]
        uri = et["uri"]
        scheduling_url = et["scheduling_url"]

        print(f"      - {duration} min: {name}")

        # Check if already exists
        stmt = select(TherapistEventType).where(
            TherapistEventType.calendly_event_type_uri == uri
        )
        existing = db.exec(stmt).first()

        if existing:
            # Update existing
            existing.duration_minutes = duration
            existing.scheduling_url = scheduling_url
            existing.is_active = et["active"]
            db.add(existing)
            print(f"        ↻ Updated existing record")
        else:
            # Create new
            new_event_type = TherapistEventType(
                therapist_id=therapist.id,
                calendly_event_type_uri=uri,
                duration_minutes=duration,
                scheduling_url=scheduling_url,
                is_active=et["active"],
            )
            db.add(new_event_type)
            print(f"        ✨ Created new record")

        synced += 1

    db.commit()
    print(f"   ✅ Sync complete! {synced} event type(s) synced.")
    return synced


def main():
    parser = argparse.ArgumentParser(description="Sync Calendly event types for therapists")
    parser.add_argument(
        "--therapist-id",
        type=int,
        help="Sync specific therapist by ID",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Sync all active therapists",
    )
    args = parser.parse_args()

    if not args.therapist_id and not args.all:
        print("❌ Error: Must specify --therapist-id or --all")
        parser.print_help()
        sys.exit(1)

    print("="*60)
    print("Calendly Event Type Sync")
    print("="*60)

    with Session(engine) as db:
        if args.therapist_id:
            # Sync single therapist
            stmt = select(Therapist).where(Therapist.id == args.therapist_id)
            therapist = db.exec(stmt).first()

            if not therapist:
                print(f"❌ Therapist ID {args.therapist_id} not found")
                sys.exit(1)

            synced = sync_therapist_event_types(db, therapist)

        elif args.all:
            # Sync all active therapists
            stmt = select(Therapist).where(Therapist.is_active == True)  # noqa: E712
            therapists = db.exec(stmt).all()

            if not therapists:
                print("⚠️  No active therapists found")
                sys.exit(0)

            print(f"Found {len(therapists)} active therapist(s)\n")

            total_synced = 0
            for therapist in therapists:
                synced = sync_therapist_event_types(db, therapist)
                total_synced += synced

            print("\n" + "="*60)
            print(f"✅ Total: {total_synced} event types synced across {len(therapists)} therapists")

    print("="*60)


if __name__ == "__main__":
    main()
