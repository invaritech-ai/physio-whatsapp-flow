# 📋 Setup Guide - Follow This Order

This is the **master setup guide** for the Physio WhatsApp Flow system. Follow these steps in order.

---

## 🎯 Quick Start Checklist

- [ ] **Step 1**: Environment setup (Python, Redis, PostgreSQL)
- [ ] **Step 2**: Database configuration
- [ ] **Step 3**: Encryption key generation
- [ ] **Step 4**: Twilio WhatsApp setup
- [ ] **Step 5**: Calendly integration
- [ ] **Step 6**: Neon Auth configuration
- [ ] **Step 7**: Run migrations
- [ ] **Step 8**: Seed initial data
- [ ] **Step 9**: Deploy and test

---

## 📚 Documentation Order

Follow these documents in numbered order:

### **Phase 1: Infrastructure Setup**

#### [01-environment-setup.md](01-environment-setup.md)
- Install Python 3.10+
- Install Redis
- Install PostgreSQL (Neon recommended)
- Clone repository
- Create virtual environment
- Install dependencies

#### [02-database-setup.md](02-database-setup.md)
- Configure DATABASE_URL
- Understand database models
- Run initial migrations

#### [03-encryption-setup.md](03-encryption-setup.md) ⚠️ **CRITICAL**
- Generate encryption key
- Add to .env
- Understand security implications

---

### **Phase 2: External Services**

#### [04-twilio-setup.md](04-twilio-setup.md)
- Create Twilio account
- Get WhatsApp sandbox credentials
- Configure webhook URLs
- Test message sending

#### [05-calendly-setup.md](05-calendly-setup.md)
- Create Calendly organization account
- Generate organization API token (optional)
- Register webhook subscription
- Understand event types

#### [06-neon-auth-setup.md](06-neon-auth-setup.md)
- Set up Neon database with Auth
- Configure JWKS endpoint
- Create initial admin user
- Test JWT authentication

---

### **Phase 3: Data & Deployment**

#### [07-seed-data.md](07-seed-data.md)
- Create specialties
- Create test therapists (optional)
- Test data verification

#### [08-deployment.md](08-deployment.md)
- Environment variables checklist
- Database migrations
- Celery worker setup
- Webhook configuration
- Health checks

---

### **Phase 4: Usage Guides**

#### [09-therapist-onboarding.md](therapist-onboarding.md)
- Admin: Add therapist to Calendly
- Therapist: Create event types
- Therapist: Self-service onboarding wizard
- Verify setup

#### [10-admin-operations.md](10-admin-operations.md)
- Manage specialties
- Manage therapists
- View sessions
- Manual overrides

#### [11-bot-flow.md](11-bot-flow.md)
- How the WhatsApp bot works
- Customer journey
- Matching algorithm
- Troubleshooting

---

### **Phase 5: Advanced Topics**

#### [12-api-reference.md](12-api-reference.md)
- Admin API endpoints
- Therapist API endpoints
- Webhook endpoints
- Authentication

#### [13-matching-algorithm.md](v1-matching-spec.md)
- How therapist matching works
- Scoring system
- Fallback cascade
- Audit trails

#### [14-security.md](14-security.md)
- Authentication & authorization
- Encrypted data storage
- Webhook signature verification
- Rate limiting

---

## 🚀 Quick Deploy (For Experienced Devs)

If you're familiar with the stack:

```bash
# 1. Clone and setup
git clone <repo>
cd physio-whatsapp-flow
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# 2. Generate encryption key
python scripts/generate_encryption_key.py

# 3. Copy and configure .env
cp .env.example .env
# Edit .env with your keys (DATABASE_URL, ENCRYPTION_KEY, TWILIO_*, CALENDLY_*, NEON_*)

# 4. Setup database
alembic upgrade head
python scripts/seed_specialties.py  # Create initial specialties

# 5. Start services
# Terminal 1: Redis
redis-server

# Terminal 2: Celery worker
celery -A app.celery.worker.celery_app worker --loglevel=info

# Terminal 3: FastAPI server
uvicorn app.main:app --reload

# 6. Test
curl http://localhost:8000/health
```

---

## ⚠️ Critical Requirements

### **Must-Have Before Going Live**

1. ✅ **ENCRYPTION_KEY set** - Without this, therapist onboarding fails
2. ✅ **DATABASE_URL to PostgreSQL** - SQLite is dev-only
3. ✅ **Twilio credentials** - WhatsApp bot won't work without them
4. ✅ **Neon Auth configured** - Web UI login requires JWT validation
5. ✅ **Redis running** - Celery tasks need Redis
6. ✅ **Webhooks registered** - Calendly bookings won't sync without webhooks

### **Recommended But Optional**

- Organization-level Calendly token (for therapists in same org)
- Storage endpoint (S3/R2) for future file uploads
- Monitoring (Sentry, LogRocket, etc.)

---

## 🆘 Getting Help

**Before asking for help:**
1. Check logs: `tail -f logs/app.log`
2. Verify environment: `python scripts/check_env.py` (TODO: create this)
3. Test components individually (see Phase 2 docs)

**Common Issues:**
- "ENCRYPTION_KEY not set" → See [03-encryption-setup.md](03-encryption-setup.md)
- "Invalid JWT" → Check [06-neon-auth-setup.md](06-neon-auth-setup.md)
- "Twilio webhook failed" → Verify PUBLIC_BASE_URL and webhook signature
- "No therapists matched" → Check specialty assignments and therapist.is_active

---

## 📞 Support

- **Documentation Issues**: Open issue on GitHub
- **Feature Requests**: Create discussion on GitHub
- **Bugs**: File issue with logs and steps to reproduce

---

## 🎓 Learning Path

**New to the stack?**
1. Read [01-environment-setup.md](01-environment-setup.md) carefully
2. Follow each phase in order
3. Don't skip Phase 2 - external services are critical
4. Test each component as you go

**Experienced developer?**
- Jump to [Quick Deploy](#-quick-deploy-for-experienced-devs)
- Review [08-deployment.md](08-deployment.md) for production
- Check [12-api-reference.md](12-api-reference.md) for API docs

---

## ✅ Setup Verification

After setup, verify everything works:

```bash
# 1. Health check
curl http://localhost:8000/health

# 2. Database check
alembic current

# 3. Encryption check
python -c "from app.core.encryption import encrypt_string; print(encrypt_string('test'))"

# 4. Redis check
redis-cli ping

# 5. Celery check
celery -A app.celery.worker.celery_app inspect active

# 6. Webhook check (if deployed)
curl https://yourdomain.com/api/v1/webhooks/calendly
```

All checks should pass before proceeding to onboard therapists.

---

## 🔄 Next Steps After Setup

1. **Create specialties**: `python scripts/seed_specialties.py`
2. **Invite therapists**: Add to Calendly, share invitation
3. **Test bot flow**: Send "hi" to WhatsApp number
4. **Monitor webhooks**: Watch logs for Calendly events
5. **Onboard first therapist**: Follow [09-therapist-onboarding.md](therapist-onboarding.md)

---

**👉 Start with [01-environment-setup.md](01-environment-setup.md)**
