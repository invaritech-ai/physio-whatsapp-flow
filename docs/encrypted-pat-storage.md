# Encrypted PAT Storage

## Overview

Starting from this version, therapist Calendly Personal Access Tokens (PATs) are **encrypted and stored** in the database. This gives the system full control over querying each therapist's Calendly data without depending on organization-level tokens.

## Why Store PAT?

1. **Independent Calendly Accounts**: Therapists may have their own Calendly accounts (not under the same organization)
2. **Full Control**: Can query availability, event types, and scheduled events for each therapist independently
3. **Service Provider Model**: Therapists manage their own Calendly accounts - we just need their PAT

## Security

- **Encryption**: PATs are encrypted using Fernet (symmetric encryption)
- **Storage**: Only encrypted ciphertext is stored in `therapist.calendly_pat_encrypted`
- **Decryption**: PAT is decrypted only when needed for API calls (never logged)
- **Key Management**: Encryption key stored in `ENCRYPTION_KEY` environment variable

## Setup

### 1. Generate Encryption Key

```bash
python scripts/generate_encryption_key.py
```

This outputs a Fernet key like:
```
ENCRYPTION_KEY=aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uVwXyZ1234567890=
```

### 2. Add to .env

```bash
# .env
ENCRYPTION_KEY=aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uVwXyZ1234567890=
```

**⚠️ CRITICAL:**
- Keep this key secret
- Store in password manager
- DO NOT commit to version control
- If lost, you cannot decrypt existing PATs (therapists must re-onboard)

### 3. Run Migration

```bash
alembic upgrade head
```

This adds `calendly_pat_encrypted` column to `therapist` table.

## Usage

### During Onboarding

```python
# POST /therapist/onboarding/complete
{
  "calendly_pat": "eyJraWQiOiIxY2UxZTEzNj...",  # Plain PAT
  "specialty_ids": [1, 2]
}
```

**What happens:**
1. PAT validated against Calendly API
2. PAT encrypted using Fernet
3. Encrypted ciphertext stored in `therapist.calendly_pat_encrypted`
4. Plain PAT discarded (never stored)

### After Onboarding

When re-syncing event types:
```python
POST /therapist/sync-event-types
```

**What happens:**
1. Retrieves `therapist.calendly_pat_encrypted`
2. Decrypts to get plain PAT
3. Uses PAT to query Calendly API
4. Updates event types in database

## Code Example

```python
from app.core.encryption import encrypt_string, decrypt_string

# Encrypt before storing
encrypted = encrypt_string("my_secret_pat")
therapist.calendly_pat_encrypted = encrypted
db.add(therapist)
db.commit()

# Decrypt when needed
if therapist.calendly_pat_encrypted:
    plain_pat = decrypt_string(therapist.calendly_pat_encrypted)
    # Use plain_pat for API calls
```

## Migration Path

### Existing Therapists (No PAT Stored)

If you have therapists onboarded **before** this change:

**Option 1: Re-onboard**
- Therapist goes through onboarding wizard again
- Provides PAT → System stores encrypted PAT

**Option 2: Admin Update** (if you have their PAT)
```python
from app.core.encryption import encrypt_string
from app.models import Therapist

therapist = db.get(Therapist, therapist_id)
therapist.calendly_pat_encrypted = encrypt_string("therapist_pat_here")
db.add(therapist)
db.commit()
```

## Fallback Behavior

If `therapist.calendly_pat_encrypted` is `None`:
- System falls back to org-level token (`CALENDLY_API_TOKEN`)
- Works if therapist is in same organization

## Security Best Practices

1. ✅ **Rotate Keys Periodically**: Update `ENCRYPTION_KEY` annually (requires re-encrypting all PATs)
2. ✅ **Monitor Access**: Log when PATs are decrypted (audit trail)
3. ✅ **Secure Backups**: Ensure database backups are encrypted at rest
4. ✅ **Key Separation**: Use different keys for dev/staging/production
5. ✅ **Never Log**: Never log decrypted PATs (only log "PAT decrypted for therapist X")

## Troubleshooting

### "ENCRYPTION_KEY not set in environment"

**Cause**: Missing `ENCRYPTION_KEY` in `.env`

**Fix**:
```bash
python scripts/generate_encryption_key.py
# Copy key to .env
```

### "Invalid token" (cryptography.fernet.InvalidToken)

**Cause**: Encryption key changed or data corrupted

**Fix**:
- If key was rotated: Re-encrypt all PATs with new key
- If corrupted: Therapist must re-onboard to provide new PAT

### PAT Rotation by Therapist

If therapist generates new PAT in Calendly:

**Solution**: Re-onboard or update via admin
```python
# Option 1: Therapist re-onboards
POST /therapist/onboarding/complete (will fail - already onboarded)

# Option 2: Admin updates PAT
therapist.calendly_pat_encrypted = encrypt_string(new_pat)
```

**Future Enhancement**: Add endpoint for therapists to rotate their own PAT:
```
POST /therapist/rotate-pat
{
  "new_calendly_pat": "new_pat_here"
}
```

## Dependencies

- `cryptography` library (already in requirements.txt)
- Python 3.8+ (for Fernet support)
