#!/usr/bin/env python3
"""Seed test data for Phase 2 bot testing.

This script creates:
- 3 specialties (Sports Rehab, Orthopedic, Neurological)
- 3 therapists with Calendly URIs
- Specialty assignments for each therapist

Run this script to populate your database for testing the WhatsApp bot.
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select

from app.db.session import engine
from app.models import Therapist, TherapistSpecialty, TherapistSpecialtyMap, User


def seed_specialties(db: Session) -> dict[str, int]:
    """Create specialties and return name -> id mapping."""
    print("Creating specialties...")

    specialties_data = [
        {
            "name": "Sports Rehabilitation",
            "description": "Treatment for sports injuries and athletic performance",
        },
        {
            "name": "Orthopedic",
            "description": "Musculoskeletal disorders and injuries",
        },
        {
            "name": "Neurological",
            "description": "Nervous system and brain injury rehabilitation",
        },
    ]

    specialty_map = {}
    for spec_data in specialties_data:
        # Check if specialty already exists
        existing = db.exec(
            select(TherapistSpecialty).where(
                TherapistSpecialty.name == spec_data["name"]
            )
        ).first()

        if existing:
            print(f"  ✓ Specialty '{spec_data['name']}' already exists (id={existing.id})")
            specialty_map[spec_data["name"]] = existing.id
        else:
            specialty = TherapistSpecialty(**spec_data, is_active=True)
            db.add(specialty)
            db.commit()
            db.refresh(specialty)
            print(f"  ✓ Created specialty '{specialty.name}' (id={specialty.id})")
            specialty_map[specialty.name] = specialty.id

    return specialty_map


def seed_therapists(db: Session) -> list[int]:
    """Create therapists and return list of IDs."""
    print("\nCreating therapists...")

    therapists_data = [
        {
            "neon_auth_sub": "auth-dr-sarah-smith",
            "email": "dr.sarah.smith@movement.clinic",
            "display_name": "Dr. Sarah Smith",
            "calendly_user_uri": "https://api.calendly.com/users/SARAH_SMITH_123",
        },
        {
            "neon_auth_sub": "auth-dr-michael-jones",
            "email": "dr.michael.jones@movement.clinic",
            "display_name": "Dr. Michael Jones",
            "calendly_user_uri": "https://api.calendly.com/users/MICHAEL_JONES_456",
        },
        {
            "neon_auth_sub": "auth-dr-emily-wong",
            "email": "dr.emily.wong@movement.clinic",
            "display_name": "Dr. Emily Wong",
            "calendly_user_uri": "https://api.calendly.com/users/EMILY_WONG_789",
        },
    ]

    therapist_ids = []
    for therapist_data in therapists_data:
        # Check if user already exists
        existing_user = db.exec(
            select(User).where(User.email == therapist_data["email"])
        ).first()

        if existing_user:
            print(f"  ⚠ User '{therapist_data['email']}' already exists, skipping")
            # Find associated therapist
            existing_therapist = db.exec(
                select(Therapist).where(Therapist.user_id == existing_user.id)
            ).first()
            if existing_therapist:
                therapist_ids.append(existing_therapist.id)
            continue

        # Create User
        user = User(
            neon_auth_sub=therapist_data["neon_auth_sub"],
            email=therapist_data["email"],
            display_name=therapist_data["display_name"],
            role="therapist",
            is_active=True,
        )
        db.add(user)
        db.flush()

        # Create Therapist
        therapist = Therapist(
            user_id=user.id,
            display_name=therapist_data["display_name"],
            calendly_user_uri=therapist_data["calendly_user_uri"],
            is_active=True,
        )
        db.add(therapist)
        db.commit()
        db.refresh(therapist)

        print(f"  ✓ Created therapist '{therapist.display_name}' (id={therapist.id})")
        therapist_ids.append(therapist.id)

    return therapist_ids


def assign_specialties(db: Session, therapist_ids: list[int], specialty_map: dict[str, int]):
    """Assign specialties to therapists."""
    print("\nAssigning specialties to therapists...")

    # Assignment plan:
    # Dr. Sarah Smith (id=0) -> Sports Rehab, Orthopedic
    # Dr. Michael Jones (id=1) -> Orthopedic, Neurological
    # Dr. Emily Wong (id=2) -> Sports Rehab, Neurological

    assignments = [
        (therapist_ids[0], [specialty_map["Sports Rehabilitation"], specialty_map["Orthopedic"]]),
        (therapist_ids[1], [specialty_map["Orthopedic"], specialty_map["Neurological"]]),
        (therapist_ids[2], [specialty_map["Sports Rehabilitation"], specialty_map["Neurological"]]),
    ]

    for therapist_id, specialty_ids in assignments:
        therapist = db.get(Therapist, therapist_id)
        if not therapist:
            print(f"  ⚠ Therapist id={therapist_id} not found, skipping")
            continue

        for specialty_id in specialty_ids:
            # Check if assignment already exists
            existing = db.exec(
                select(TherapistSpecialtyMap).where(
                    TherapistSpecialtyMap.therapist_id == therapist_id,
                    TherapistSpecialtyMap.specialty_id == specialty_id,
                )
            ).first()

            if existing:
                specialty = db.get(TherapistSpecialty, specialty_id)
                print(f"  ✓ {therapist.display_name} already has '{specialty.name}'")
                continue

            # Create assignment
            assignment = TherapistSpecialtyMap(
                therapist_id=therapist_id,
                specialty_id=specialty_id,
            )
            db.add(assignment)
            db.commit()

            specialty = db.get(TherapistSpecialty, specialty_id)
            print(f"  ✓ Assigned '{specialty.name}' to {therapist.display_name}")


def print_summary(db: Session):
    """Print summary of seeded data."""
    print("\n" + "=" * 60)
    print("SEED DATA SUMMARY")
    print("=" * 60)

    # Count specialties
    specialties = db.exec(select(TherapistSpecialty)).all()
    print(f"\n✓ Specialties: {len(specialties)}")
    for spec in specialties:
        print(f"  - {spec.name} (id={spec.id}, active={spec.is_active})")

    # Count therapists
    therapists = db.exec(select(Therapist)).all()
    print(f"\n✓ Therapists: {len(therapists)}")
    for therapist in therapists:
        # Get assigned specialties
        stmt = (
            select(TherapistSpecialty)
            .join(TherapistSpecialtyMap)
            .where(TherapistSpecialtyMap.therapist_id == therapist.id)
        )
        assigned_specs = db.exec(stmt).all()
        spec_names = ", ".join([s.name for s in assigned_specs])

        print(f"  - {therapist.display_name} (id={therapist.id}, active={therapist.is_active})")
        print(f"    Specialties: {spec_names}")
        print(f"    Calendly URI: {therapist.calendly_user_uri}")

    print("\n" + "=" * 60)
    print("✓ Database seeded successfully!")
    print("✓ Ready for Phase 2 bot testing")
    print("=" * 60 + "\n")


def main():
    """Main seeding function."""
    print("\n" + "=" * 60)
    print("SEEDING TEST DATA FOR PHASE 2 BOT")
    print("=" * 60 + "\n")

    with Session(engine) as db:
        try:
            # Step 1: Create specialties
            specialty_map = seed_specialties(db)

            # Step 2: Create therapists
            therapist_ids = seed_therapists(db)

            # Step 3: Assign specialties
            if therapist_ids:
                assign_specialties(db, therapist_ids, specialty_map)

            # Step 4: Print summary
            print_summary(db)

        except Exception as e:
            print(f"\n❌ Error during seeding: {e}")
            db.rollback()
            raise


if __name__ == "__main__":
    main()
