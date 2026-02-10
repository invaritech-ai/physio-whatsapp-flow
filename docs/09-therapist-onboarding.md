# Therapist Onboarding Guide

This document explains how to onboard new therapists to the physio booking system.

---

## Overview

Each therapist needs:
1. **Calendly account** (added as a seat to your organization)
2. **Database record** (via admin API)
3. **Specialty assignments** (via admin API)
4. **Event types synced** (via sync script)

---

## Step 1: Add Therapist to Calendly

### 1.1 Add User Seat in Calendly

1. Go to https://calendly.com/app/organization/team
2. Click **"Invite Team Member"**
3. Enter therapist's email address
4. Assign role: **"User"** (not Admin)
5. Send invitation

The therapist will receive an email to create their Calendly account.

### 1.2 Therapist Sets Up Event Types

Once the therapist has accepted the invitation and logged in, they must create 3 event types:

**Required event types:**
- **30-minute Session** (duration: 30 minutes)
- **45-minute Session** (duration: 45 minutes)
- **60-minute Session** (duration: 60 minutes)

**Important settings for each event type:**
- ✅ Set availability (when they can work)
- ✅ Enable "Collect phone number" in booking form questions (required to link bookings to clients)
- ✅ Set event location (e.g., clinic address, video call link)
- ✅ Make event type **Active**

### 1.3 Get Therapist's Calendly User URI

Once the therapist has their Calendly account set up, you need their **User URI**:

**Option A: Use the API (Recommended)**

Have the therapist generate a Personal Access Token:
1. Log into Calendly
2. Go to **Integrations** → **API & Webhooks**
3. Click **"Generate New Token"**
4. Copy the token

Then run:
```bash
curl https://api.calendly.com/users/me \
  -H "Authorization: Bearer THERAPIST_TOKEN"
```

The response contains their `uri` (e.g., `https://api.calendly.com/users/XXXXX`)

**Option B: Use Organization Admin Access**

If you're the organization admin, you can list all users:
```bash
PYTHONPATH=. python scripts/list_organization_users.py
```

This will show all users in your organization with their URIs.

---

## Step 2: Create Therapist Record in Database

### 2.1 Get Neon Auth ID

The therapist must first log into the web UI (admin panel) using Neon Auth. This creates their Neon Auth identity.

Once they've logged in once, you can find their `neon_auth_sub` in your Neon Auth dashboard or database.

### 2.2 Create Therapist via API

Make a POST request to create the therapist:

```bash
POST /admin/therapists
Content-Type: application/json

{
  "neon_auth_sub": "auth|XXXXX",  # From Neon Auth
  "email": "therapist@example.com",
  "display_name": "Dr. Sarah Johnson",
  "calendly_user_uri": "https://api.calendly.com/users/XXXXX"  # From Step 1.3
}
```

**Example using curl:**
```bash
curl -X POST http://your-domain.com/admin/therapists \
  -H "Content-Type: application/json" \
  -d '{
    "neon_auth_sub": "auth|abc123",
    "email": "sarah@clinic.com",
    "display_name": "Dr. Sarah Johnson",
    "calendly_user_uri": "https://api.calendly.com/users/84857944-e6a3-4ea6-b87f-b0dccee65552"
  }'
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": 2,
    "user_id": 2,
    "display_name": "Dr. Sarah Johnson",
    "is_active": true,
    "calendly_user_uri": "https://api.calendly.com/users/84857944-e6a3-4ea6-b87f-b0dccee65552",
    "specialties": [],
    "created_at": "2026-02-09T08:00:00Z"
  }
}
```

Save the `therapist.id` (in this example: `2`) for the next steps.

---

## Step 3: Assign Specialties

### 3.1 List Available Specialties

First, see what specialties exist:

```bash
GET /admin/specialties
```

**Example:**
```bash
curl http://your-domain.com/admin/specialties
```

**Response:**
```json
{
  "status": "success",
  "data": [
    {"id": 1, "name": "Sports Rehabilitation", "is_active": true},
    {"id": 2, "name": "Women's Health", "is_active": true},
    {"id": 3, "name": "Pediatric Physiotherapy", "is_active": true}
  ]
}
```

### 3.2 Assign Specialties to Therapist

Add each specialty the therapist is qualified for:

```bash
POST /admin/therapists/{therapist_id}/specialties
Content-Type: application/json

{
  "specialty_id": 1
}
```

**Example (assign Sports Rehab and Women's Health):**
```bash
# Assign Sports Rehabilitation
curl -X POST http://your-domain.com/admin/therapists/2/specialties \
  -H "Content-Type: application/json" \
  -d '{"specialty_id": 1}'

# Assign Women's Health
curl -X POST http://your-domain.com/admin/therapists/2/specialties \
  -H "Content-Type: application/json" \
  -d '{"specialty_id": 2}'
```

---

## Step 4: Sync Calendly Event Types

This step fetches the therapist's event types from Calendly and stores them in the database so the bot can generate booking links.

### 4.1 Run Event Type Sync Script

```bash
PYTHONPATH=. python scripts/sync_event_types.py --therapist-id 2
```

Or sync all therapists at once:
```bash
PYTHONPATH=. python scripts/sync_event_types.py --all
```

**What this does:**
- Fetches 30min, 45min, 60min event types from therapist's Calendly
- Creates `TherapistEventType` records in database
- Links event types to therapist
- Stores scheduling URLs

**Output:**
```
Syncing event types for Dr. Sarah Johnson (ID: 2)
✅ Found 3 event types:
   - 30 Minute Session → https://calendly.com/sarah-clinic/30min
   - 45 Minute Session → https://calendly.com/sarah-clinic/45min
   - 60 Minute Session → https://calendly.com/sarah-clinic/60min
✅ Sync complete! 3 event types added.
```

---

## Step 5: Verify Setup

### 5.1 Check Therapist Record

```bash
GET /admin/therapists/{therapist_id}
```

Should return:
- ✅ Therapist details
- ✅ Assigned specialties
- ✅ Calendly user URI
- ✅ `is_active: true`

### 5.2 Test Matching

Create a test booking flow via WhatsApp bot:
1. Send "book" to the bot
2. Select a specialty that the new therapist has
3. Choose duration and days
4. **Verify:** New therapist appears as a match option

### 5.3 Test Calendly Booking

1. Complete bot flow to get Calendly link
2. Click the link and book a session
3. **Verify:** Session appears in database with correct therapist_id
4. **Verify:** Webhook created the session (check `source: "calendly"`)

---

## Troubleshooting

### Therapist not appearing in matches

**Possible causes:**
1. ❌ `is_active = false` → Update via `PATCH /admin/therapists/{id}`
2. ❌ No specialties assigned → Check specialties via `GET /admin/therapists/{id}`
3. ❌ Event types not synced → Run sync script

**Fix:**
```bash
# Check therapist status
curl http://your-domain.com/admin/therapists/2

# Activate if needed
curl -X PATCH http://your-domain.com/admin/therapists/2 \
  -H "Content-Type: application/json" \
  -d '{"is_active": true}'
```

### Calendly link not working

**Possible causes:**
1. ❌ Event types not synced → Run `sync_event_types.py`
2. ❌ Wrong `calendly_user_uri` → Update therapist record
3. ❌ Event type not active in Calendly → Check Calendly dashboard

**Fix:**
```bash
# Re-sync event types
PYTHONPATH=. python scripts/sync_event_types.py --therapist-id 2
```

### Webhook not creating sessions

**Possible causes:**
1. ❌ Webhook not registered → Run setup script
2. ❌ `calendly_event_uri` mismatch → Check logs
3. ❌ Client phone not found → Ensure "Phone Number" field in Calendly booking form

**Debug:**
```bash
# Check webhook logs
tail -f logs/app.log | grep calendly

# Test webhook manually (see docs/api-guide.md)
```

---

## Offboarding a Therapist

To deactivate a therapist (keep records but prevent new bookings):

```bash
PATCH /admin/therapists/{therapist_id}
Content-Type: application/json

{
  "is_active": false
}
```

**Example:**
```bash
curl -X PATCH http://your-domain.com/admin/therapists/2 \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'
```

**Effects:**
- ✅ Therapist excluded from matching engine
- ✅ Existing sessions remain intact
- ✅ Can be reactivated later (`is_active: true`)

---

## Quick Reference: Complete Onboarding Checklist

- [ ] Add therapist as Calendly user seat
- [ ] Therapist creates 3 event types (30/45/60 min) with phone field
- [ ] Get therapist's Calendly User URI
- [ ] Therapist logs into web UI once (creates Neon Auth record)
- [ ] Get `neon_auth_sub` from auth system
- [ ] `POST /admin/therapists` with all details
- [ ] `POST /admin/therapists/{id}/specialties` for each specialty
- [ ] Run `sync_event_types.py --therapist-id {id}`
- [ ] Verify via `GET /admin/therapists/{id}`
- [ ] Test booking flow via WhatsApp bot

---

## Scripts Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `setup_calendly.py` | Initial Calendly setup, webhook registration | `PYTHONPATH=. python scripts/setup_calendly.py` |
| `sync_event_types.py` | Sync therapist event types from Calendly | `PYTHONPATH=. python scripts/sync_event_types.py --therapist-id 2` |
| `list_organization_users.py` | List all Calendly users in org | `PYTHONPATH=. python scripts/list_organization_users.py` |

---

## Notes

- **Calendly Standard Plan** required ($10/seat/month) for API access and webhooks
- **Maximum 4 seats** in your current plan (1 used, 3 available)
- Each therapist must have their own Calendly account (cannot share)
- Event type names don't have to match exactly, but must include duration (30, 45, 60)
- Phone number field in Calendly is **required** to link bookings to clients
