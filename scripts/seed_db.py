#!/usr/bin/env python3
"""Seed the database with initial data (specialties + first admin user).

Usage:
    PYTHONPATH=. python scripts/seed_db.py --neon-auth-sub <NEON_AUTH_SUB>

    The neon_auth_sub is your Neon Auth subject ID (found in the JWT 'sub' claim).
    If omitted, only specialties are seeded and admin creation is skipped.
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select

from app.db.session import engine
from app.models import TherapistSpecialty, User


SPECIALTIES = [
    {
        "name": "Sports Rehabilitation",
        "description": "Treatment for sports injuries and athletic performance enhancement",
    },
    {
        "name": "Women's Health",
        "description": "Specialized care for women's health issues including pre/post-natal",
    },
    {
        "name": "Pediatric Physiotherapy",
        "description": "Treatment for children and adolescents",
    },
    {
        "name": "Orthopedic Rehabilitation",
        "description": "Recovery from orthopedic surgeries and musculoskeletal conditions",
    },
    {
        "name": "Neurological Rehabilitation",
        "description": "Treatment for neurological conditions and stroke recovery",
    },
    {
        "name": "Geriatric Physiotherapy",
        "description": "Specialized care for elderly patients",
    },
    {
        "name": "Manual Therapy",
        "description": "Hands-on treatment techniques for pain relief and mobility",
    },
    {
        "name": "Dry Needling / Acupuncture",
        "description": "Trigger point therapy and acupuncture techniques",
    },
]

ADMIN_USER = {
    "email": "avishek@invaritech.ai",
    "display_name": "Avishek Majumder",
    "role": "admin",
}


def seed_specialties(db: Session) -> None:
    """Create initial specialties (idempotent)."""
    print("Seeding specialties...")
    created = 0
    skipped = 0

    for spec_data in SPECIALTIES:
        existing = db.exec(
            select(TherapistSpecialty).where(TherapistSpecialty.name == spec_data["name"])
        ).first()

        if existing:
            print(f"  skip: {spec_data['name']} (already exists, id={existing.id})")
            skipped += 1
        else:
            specialty = TherapistSpecialty(
                name=spec_data["name"],
                description=spec_data.get("description"),
                is_active=True,
            )
            db.add(specialty)
            print(f"  add:  {spec_data['name']}")
            created += 1

    db.commit()
    print(f"  => {created} created, {skipped} skipped\n")


def seed_admin(db: Session, neon_auth_sub: str) -> None:
    """Create the first admin user (idempotent)."""
    print("Seeding admin user...")

    # Check by email
    existing = db.exec(
        select(User).where(User.email == ADMIN_USER["email"])
    ).first()

    if existing:
        print(f"  skip: {ADMIN_USER['email']} (already exists, id={existing.id}, role={existing.role})")
        # Update neon_auth_sub if it changed
        if existing.neon_auth_sub != neon_auth_sub:
            existing.neon_auth_sub = neon_auth_sub
            db.add(existing)
            db.commit()
            print(f"  update: neon_auth_sub updated to {neon_auth_sub}")
        print()
        return

    user = User(
        neon_auth_sub=neon_auth_sub,
        email=ADMIN_USER["email"],
        display_name=ADMIN_USER["display_name"],
        role=ADMIN_USER["role"],
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"  add:  {user.display_name} <{user.email}> (id={user.id}, role={user.role})")
    print()


def print_summary(db: Session) -> None:
    """Print current DB state."""
    print("=" * 50)
    print("DATABASE STATE")
    print("=" * 50)

    specialties = db.exec(
        select(TherapistSpecialty).order_by(TherapistSpecialty.name)
    ).all()
    print(f"\nSpecialties ({len(specialties)}):")
    for s in specialties:
        print(f"  {s.id}. {s.name}")

    users = db.exec(select(User).order_by(User.id)).all()
    print(f"\nUsers ({len(users)}):")
    for u in users:
        print(f"  {u.id}. {u.display_name} <{u.email}> [{u.role}] active={u.is_active}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Seed database with initial data")
    parser.add_argument(
        "--neon-auth-sub",
        help="Neon Auth subject ID for the admin user (JWT 'sub' claim)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("SEED DATABASE")
    print("=" * 50 + "\n")

    with Session(engine) as db:
        seed_specialties(db)

        if args.neon_auth_sub:
            seed_admin(db, args.neon_auth_sub)
        else:
            print("Skipping admin user (no --neon-auth-sub provided)\n")

        print_summary(db)

    print("Done.\n")


if __name__ == "__main__":
    main()
