"""Seed initial specialties into the database.

Usage:
    PYTHONPATH=. python scripts/seed_specialties.py
"""

from sqlmodel import Session, select

from app.core.config import settings
from app.db.session import engine
from app.models import TherapistSpecialty


def seed_specialties():
    """Create initial specialties."""
    specialties_data = [
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

    print("=" * 60)
    print("Seeding Specialties")
    print("=" * 60)

    with Session(engine) as db:
        created = 0
        skipped = 0

        for spec_data in specialties_data:
            # Check if specialty already exists
            stmt = select(TherapistSpecialty).where(
                TherapistSpecialty.name == spec_data["name"]
            )
            existing = db.exec(stmt).first()

            if existing:
                print(f"⏭️  Skipped: {spec_data['name']} (already exists)")
                skipped += 1
            else:
                specialty = TherapistSpecialty(
                    name=spec_data["name"],
                    description=spec_data.get("description"),
                    is_active=True,
                )
                db.add(specialty)
                print(f"✅ Created: {spec_data['name']}")
                created += 1

        db.commit()

        print()
        print("=" * 60)
        print(f"✅ Created: {created} specialties")
        print(f"⏭️  Skipped: {skipped} specialties (already existed)")
        print("=" * 60)

        # Show all specialties
        all_specialties = db.exec(select(TherapistSpecialty)).all()
        print()
        print("📋 All Specialties:")
        for spec in all_specialties:
            print(f"  {spec.id}. {spec.name}")


if __name__ == "__main__":
    seed_specialties()
