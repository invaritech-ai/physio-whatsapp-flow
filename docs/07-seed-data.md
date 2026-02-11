# 07 - Seed Data

Seed the database with initial specialties and the first admin user.

## Prerequisites

- Database migrated: `alembic upgrade head`
- `.env` configured with `DATABASE_URL`

## Usage

```bash
# Specialties only
PYTHONPATH=. python scripts/seed_db.py

# Specialties + first admin user
PYTHONPATH=. python scripts/seed_db.py --neon-auth-sub "<your-neon-auth-sub>"
```

The `--neon-auth-sub` value is the Neon Auth subject ID (the `sub` claim from your JWT token).

## What gets seeded

### Specialties

| Name |
|------|
| Sports Rehabilitation |
| Women's Health |
| Pediatric Physiotherapy |
| Orthopedic Rehabilitation |
| Neurological Rehabilitation |
| Geriatric Physiotherapy |
| Manual Therapy |
| Dry Needling / Acupuncture |

### First admin user

| Field | Value |
|-------|-------|
| Email | avishek@invaritech.ai |
| Name | Avishek Majumder |
| Role | admin |

## Notes

- The script is **idempotent** — safe to run multiple times. Existing records are skipped.
- If the admin user already exists but the `neon_auth_sub` changed, it gets updated.
- Therapists are created later via the onboarding flow, not seeded here.
