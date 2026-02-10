"""Create a therapist account (simulates Neon Auth login + onboarding).

Usage:
    PYTHONPATH=. python scripts/create_therapist_account.py
"""

import sys

from sqlmodel import Session, select

from app.core.encryption import encrypt_string
from app.db.session import engine
from app.models import Therapist, TherapistSpecialty, TherapistSpecialtyMap, User


def create_therapist_account():
    """Interactive script to create therapist account."""
    print("=" * 60)
    print("Create Therapist Account")
    print("=" * 60)
    print()

    # Gather information
    print("Enter your details:")
    print()

    neon_auth_sub = input("Neon Auth Sub (e.g., 'auth|123abc'): ").strip()
    if not neon_auth_sub:
        print("❌ Neon Auth Sub is required")
        sys.exit(1)

    email = input("Email: ").strip()
    if not email:
        print("❌ Email is required")
        sys.exit(1)

    display_name = input("Display Name (e.g., 'Dr. Sarah Johnson'): ").strip()
    if not display_name:
        print("❌ Display name is required")
        sys.exit(1)

    calendly_user_uri = input(
        "Calendly User URI (from https://api.calendly.com/users/me): "
    ).strip()
    if not calendly_user_uri:
        print("❌ Calendly User URI is required")
        sys.exit(1)

    calendly_pat = input("Calendly Personal Access Token: ").strip()
    if not calendly_pat:
        print("❌ Calendly PAT is required")
        sys.exit(1)

    print()
    print("Available Specialties:")
    with Session(engine) as db:
        specialties = db.exec(select(TherapistSpecialty)).all()
        for spec in specialties:
            print(f"  {spec.id}. {spec.name}")

    print()
    specialty_ids_input = input(
        "Enter specialty IDs (comma-separated, e.g., '1,2,4'): "
    ).strip()
    if not specialty_ids_input:
        print("❌ At least one specialty is required")
        sys.exit(1)

    try:
        specialty_ids = [int(x.strip()) for x in specialty_ids_input.split(",")]
    except ValueError:
        print("❌ Invalid specialty IDs format")
        sys.exit(1)

    print()
    print("=" * 60)
    print("Creating Account...")
    print("=" * 60)

    with Session(engine) as db:
        # Check if user already exists
        stmt = select(User).where(User.neon_auth_sub == neon_auth_sub)
        existing_user = db.exec(stmt).first()
        if existing_user:
            print(f"❌ User with neon_auth_sub '{neon_auth_sub}' already exists")
            sys.exit(1)

        # Check if email already exists
        stmt = select(User).where(User.email == email)
        existing_email = db.exec(stmt).first()
        if existing_email:
            print(f"❌ Email '{email}' already registered")
            sys.exit(1)

        # Create User record
        user = User(
            neon_auth_sub=neon_auth_sub,
            email=email,
            display_name=display_name,
            role="therapist",
            is_active=True,
        )
        db.add(user)
        db.flush()  # Get user.id
        print(f"✅ Created User (ID: {user.id})")

        # Encrypt PAT
        encrypted_pat = encrypt_string(calendly_pat)

        # Create Therapist record
        therapist = Therapist(
            user_id=user.id,
            display_name=display_name,
            calendly_user_uri=calendly_user_uri,
            calendly_pat_encrypted=encrypted_pat,
            is_active=True,
        )
        db.add(therapist)
        db.flush()  # Get therapist.id
        print(f"✅ Created Therapist (ID: {therapist.id})")

        # Assign specialties
        for spec_id in specialty_ids:
            specialty = db.get(TherapistSpecialty, spec_id)
            if not specialty:
                print(f"⚠️  Warning: Specialty ID {spec_id} not found, skipping")
                continue

            mapping = TherapistSpecialtyMap(
                therapist_id=therapist.id, specialty_id=spec_id
            )
            db.add(mapping)
            print(f"✅ Assigned specialty: {specialty.name}")

        db.commit()

        print()
        print("=" * 60)
        print("✅ Account Created Successfully!")
        print("=" * 60)
        print()
        print("Summary:")
        print(f"  User ID: {user.id}")
        print(f"  Therapist ID: {therapist.id}")
        print(f"  Email: {email}")
        print(f"  Display Name: {display_name}")
        print(f"  Calendly URI: {calendly_user_uri}")
        print(f"  PAT Encrypted: ✅")
        print(f"  Specialties: {len(specialty_ids)}")
        print(f"  Active: ✅")
        print()
        print("🎉 You can now:")
        print("  1. Sync your event types: PYTHONPATH=. python scripts/sync_event_types.py --therapist-id", therapist.id)
        print("  2. Test the bot flow via WhatsApp")
        print("  3. Test onboarding API endpoints")


if __name__ == "__main__":
    create_therapist_account()
