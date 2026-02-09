# 03 - Encryption Setup

## ⚠️ CRITICAL: Required for Therapist Onboarding

Without an encryption key, therapist onboarding **will fail** when they try to store their Calendly Personal Access Token (PAT).

---

## 🔐 What Gets Encrypted?

**Therapist Calendly PATs** are encrypted at rest in the database using Fernet symmetric encryption.

- **Why?** Each therapist has their own independent Calendly account (not under your organization)
- **What's stored?** Only encrypted ciphertext (`therapist.calendly_pat_encrypted`)
- **How's it used?** Decrypted in-memory only when making Calendly API calls
- **Security:** PAT never logged, never stored in plaintext

---

## 🚀 Setup Steps

### **Step 1: Generate Encryption Key**

Run the key generation script:

```bash
python scripts/generate_encryption_key.py
```

**Output:**
```
============================================================
New Encryption Key Generated
============================================================

Add this to your .env file:

ENCRYPTION_KEY=aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uVwXyZ1234567890=

⚠️  WARNING:
- Keep this key secret and secure
- Store it in a password manager
- DO NOT commit it to version control
- If you lose this key, you cannot decrypt stored PATs
- Changing this key will invalidate all encrypted PATs

============================================================
```

### **Step 2: Add to .env**

Copy the generated key to your `.env` file:

```bash
# .env
ENCRYPTION_KEY=aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uVwXyZ1234567890=
```

### **Step 3: Verify Setup**

Test that encryption works:

```bash
python -c "from app.core.encryption import encrypt_string, decrypt_string; enc = encrypt_string('test'); dec = decrypt_string(enc); print('✅ Encryption working' if dec == 'test' else '❌ Encryption failed')"
```

Should output: `✅ Encryption working`

---

## 🔑 Key Management

### **Production Key**

For production environments:

1. Generate key on production server (not on dev machine)
2. Store in secure secret manager:
   - **Heroku**: Config vars
   - **AWS**: Secrets Manager or Parameter Store
   - **Docker**: Environment variable or Docker secrets
   - **Kubernetes**: Sealed secrets or external secrets operator

### **Development Key**

For local development:
- Generate a separate key for dev `.env`
- Never use production key in development
- Commit `.env.example` (without real keys), never `.env`

### **Staging Key**

For staging environment:
- Generate separate key for staging
- Keep staging and production keys different
- Use same key rotation policy as production

---

## 🔄 Key Rotation (Advanced)

If you need to rotate the encryption key:

**⚠️ WARNING:** This requires re-encrypting all stored PATs

```python
# scripts/rotate_encryption_key.py (TODO: create this)
from app.core.encryption import decrypt_string, encrypt_string
from app.models import Therapist

OLD_KEY = "old_key_here"
NEW_KEY = "new_key_here"

# For each therapist:
#   1. Decrypt PAT with old key
#   2. Re-encrypt with new key
#   3. Update database
```

**Safer approach:** Ask therapists to re-onboard (provides fresh PAT with new key).

---

## 🛡️ Security Best Practices

### **DO:**
✅ Generate unique keys for each environment (dev/staging/prod)
✅ Store keys in secret managers (never in code or config files)
✅ Rotate keys annually (with re-encryption plan)
✅ Restrict access to keys (only ops team needs access)
✅ Monitor key usage (log when keys are accessed)
✅ Backup encrypted data (but keep keys separate from backups)

### **DON'T:**
❌ Never commit keys to version control (.env should be in .gitignore)
❌ Never log decrypted PATs (only log "PAT decrypted for therapist X")
❌ Never share keys via email or Slack
❌ Never reuse keys across environments
❌ Never store keys in plain text files on servers

---

## 🧪 Testing Encryption

### **Unit Test**

```python
from app.core.encryption import encrypt_string, decrypt_string

def test_encryption():
    plaintext = "my_secret_pat_12345"
    encrypted = encrypt_string(plaintext)
    decrypted = decrypt_string(encrypted)

    assert encrypted != plaintext  # Ciphertext differs
    assert decrypted == plaintext  # Decrypts correctly
    print("✅ Encryption test passed")
```

### **Integration Test**

Test full therapist onboarding flow (covered in existing tests).

---

## 🔧 Troubleshooting

### **Error: "ENCRYPTION_KEY not set in environment"**

**Cause:** Missing `ENCRYPTION_KEY` in `.env`

**Solution:**
```bash
python scripts/generate_encryption_key.py
# Copy key to .env
```

### **Error: "Invalid token" (cryptography.fernet.InvalidToken)**

**Causes:**
1. Encryption key changed (data encrypted with different key)
2. Corrupted ciphertext in database
3. Wrong key being used

**Solutions:**
- **Key changed:** Re-encrypt all PATs or ask therapists to re-onboard
- **Corrupted data:** Ask affected therapist to re-onboard
- **Wrong key:** Verify correct key in `.env` for current environment

### **Error: "ValueError: Fernet key must be 32 url-safe base64-encoded bytes"**

**Cause:** Invalid key format

**Solution:** Re-generate key using the script:
```bash
python scripts/generate_encryption_key.py
```

---

## 📊 Key Specifications

**Algorithm:** Fernet (symmetric encryption)
- Based on AES-128 in CBC mode
- HMAC using SHA256 for authentication
- Includes timestamp for time-limited encryption (not used in our case)

**Key format:** 32 url-safe base64-encoded bytes
- Example: `aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uVwXyZ1234567890=`
- Length: 44 characters (32 bytes encoded to base64)

---

## 📖 Related Documentation

- [Encrypted PAT Storage](encrypted-pat-storage.md) - Full technical details
- [Therapist Onboarding](09-therapist-onboarding.md) - Uses encrypted PAT
- [Security Guide](14-security.md) - Overall security architecture

---

## ✅ Checklist

Before moving to next step:

- [ ] Encryption key generated
- [ ] Key added to `.env` file
- [ ] Verification test passed
- [ ] Key stored in password manager
- [ ] `.env` added to `.gitignore` (should already be there)
- [ ] Production key generated separately (when deploying)

---

**👉 Next: [04-twilio-setup.md](04-twilio-setup.md)**
