# Therapist Self-Service API Design

**Goal:** Allow therapists to complete their own onboarding through the frontend, with minimal admin intervention.

---

## Flow Overview

### Admin (One-time setup per therapist)
1. Add therapist as Calendly user seat
2. Share invitation email with therapist

### Therapist (Self-service)
1. Accept Calendly invitation, create account
2. Create 3 event types (30/45/60 min) with phone field
3. Generate Calendly Personal Access Token (PAT)
4. Log into web UI frontend (Neon Auth creates their user record)
5. **Frontend: Onboarding wizard**
   - Enter Calendly PAT
   - System fetches User URI and event types automatically
   - Select specialties from dropdown
   - Click "Complete Setup"
6. System syncs everything automatically

---

## New API Endpoints

### 1. Complete Therapist Onboarding

**Endpoint:** `POST /api/v1/therapist/onboarding/complete`

**Purpose:** Single endpoint that handles the entire onboarding in one transaction.

**Authentication:** Requires valid JWT (therapist must be logged in via Neon Auth)

**Request Body:**
```json
{
  "calendly_pat": "eyJraWQiOiIxY2UxZTEzNj...",
  "specialty_ids": [1, 2, 3]
}
```

**What it does:**
1. Validates Calendly PAT by calling Calendly API `/users/me`
2. Extracts `user_uri`, `name`, `email` from response
3. Finds or creates `Therapist` record for current user
4. Updates `therapist.calendly_user_uri`
5. Fetches event types from Calendly using the PAT
6. Creates `TherapistEventType` records (30/45/60 min)
7. Assigns `specialty_ids` to therapist
8. Sets `therapist.is_active = true`
9. Returns success with therapist profile

**Response (Success):**
```json
{
  "status": "success",
  "data": {
    "therapist_id": 2,
    "display_name": "Dr. Sarah Johnson",
    "calendly_user_uri": "https://api.calendly.com/users/XXXXX",
    "is_active": true,
    "specialties": [
      {"id": 1, "name": "Sports Rehabilitation"},
      {"id": 2, "name": "Women's Health"}
    ],
    "event_types_synced": 3,
    "event_types": [
      {"duration_minutes": 30, "scheduling_url": "https://calendly.com/sarah/30min"},
      {"duration_minutes": 45, "scheduling_url": "https://calendly.com/sarah/45min"},
      {"duration_minutes": 60, "scheduling_url": "https://calendly.com/sarah/60min"}
    ]
  }
}
```

**Response (Error):**
```json
{
  "status": "error",
  "message": "Invalid Calendly token",
  "code": "INVALID_CALENDLY_TOKEN"
}
```

**Error codes:**
- `INVALID_CALENDLY_TOKEN` - PAT is invalid or expired
- `CALENDLY_API_ERROR` - Calendly API returned an error
- `NO_EVENT_TYPES` - No event types found in Calendly (therapist needs to create them first)
- `MISSING_DURATION` - Required duration (30/45/60 min) not found
- `ALREADY_ONBOARDED` - Therapist already has Calendly URI set
- `INVALID_SPECIALTY_IDS` - One or more specialty IDs don't exist

---

### 2. Get Onboarding Status

**Endpoint:** `GET /api/v1/therapist/onboarding/status`

**Purpose:** Check if therapist has completed onboarding.

**Authentication:** Requires valid JWT

**Response:**
```json
{
  "status": "success",
  "data": {
    "is_onboarded": true,
    "has_calendly_uri": true,
    "has_event_types": true,
    "event_types_count": 3,
    "has_specialties": true,
    "specialties_count": 2,
    "is_active": true,
    "missing_steps": []
  }
}
```

Or if incomplete:
```json
{
  "status": "success",
  "data": {
    "is_onboarded": false,
    "has_calendly_uri": false,
    "has_event_types": false,
    "event_types_count": 0,
    "has_specialties": false,
    "specialties_count": 0,
    "is_active": false,
    "missing_steps": [
      "calendly_setup",
      "event_types",
      "specialties"
    ]
  }
}
```

---

### 3. Validate Calendly Token (Pre-check)

**Endpoint:** `POST /api/v1/therapist/onboarding/validate-calendly`

**Purpose:** Validate PAT and preview what will be synced (dry-run).

**Authentication:** Requires valid JWT

**Request Body:**
```json
{
  "calendly_pat": "eyJraWQiOiIxY2UxZTEzNj..."
}
```

**Response (Success):**
```json
{
  "status": "success",
  "data": {
    "valid": true,
    "user_uri": "https://api.calendly.com/users/XXXXX",
    "name": "Sarah Johnson",
    "email": "sarah@clinic.com",
    "event_types_found": 3,
    "event_types": [
      {"duration_minutes": 30, "name": "30 Minute Session"},
      {"duration_minutes": 45, "name": "45 Minute Session"},
      {"duration_minutes": 60, "name": "60 Minute Session"}
    ],
    "warnings": []
  }
}
```

**Response (Missing event types):**
```json
{
  "status": "success",
  "data": {
    "valid": true,
    "user_uri": "https://api.calendly.com/users/XXXXX",
    "name": "Sarah Johnson",
    "email": "sarah@clinic.com",
    "event_types_found": 1,
    "event_types": [
      {"duration_minutes": 30, "name": "30 Minute Session"}
    ],
    "warnings": [
      "Missing 45-minute event type",
      "Missing 60-minute event type"
    ]
  }
}
```

---

### 4. Re-sync Event Types

**Endpoint:** `POST /api/v1/therapist/sync-event-types`

**Purpose:** Re-sync event types if therapist adds/updates them in Calendly.

**Authentication:** Requires valid JWT

**Request Body:** (empty)

**Response:**
```json
{
  "status": "success",
  "data": {
    "event_types_synced": 3,
    "event_types": [
      {"duration_minutes": 30, "scheduling_url": "https://calendly.com/sarah/30min"},
      {"duration_minutes": 45, "scheduling_url": "https://calendly.com/sarah/45min"},
      {"duration_minutes": 60, "scheduling_url": "https://calendly.com/sarah/60min"}
    ]
  }
}
```

---

### 5. Update Specialties

**Endpoint:** `PATCH /api/v1/therapist/specialties`

**Purpose:** Update therapist's specialties after onboarding.

**Authentication:** Requires valid JWT

**Request Body:**
```json
{
  "specialty_ids": [1, 3, 5]
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "specialties": [
      {"id": 1, "name": "Sports Rehabilitation"},
      {"id": 3, "name": "Pediatric Physiotherapy"},
      {"id": 5, "name": "Orthopedic Rehabilitation"}
    ]
  }
}
```

---

### 6. Get Current Therapist Profile

**Endpoint:** `GET /api/v1/therapist/me`

**Purpose:** Get current therapist's full profile.

**Authentication:** Requires valid JWT

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": 2,
    "user_id": 2,
    "display_name": "Dr. Sarah Johnson",
    "email": "sarah@clinic.com",
    "is_active": true,
    "calendly_user_uri": "https://api.calendly.com/users/XXXXX",
    "specialties": [
      {"id": 1, "name": "Sports Rehabilitation"},
      {"id": 2, "name": "Women's Health"}
    ],
    "event_types": [
      {
        "id": 5,
        "duration_minutes": 30,
        "scheduling_url": "https://calendly.com/sarah/30min",
        "is_active": true
      },
      {
        "id": 6,
        "duration_minutes": 45,
        "scheduling_url": "https://calendly.com/sarah/45min",
        "is_active": true
      },
      {
        "id": 7,
        "duration_minutes": 60,
        "scheduling_url": "https://calendly.com/sarah/60min",
        "is_active": true
      }
    ],
    "created_at": "2026-02-09T08:00:00Z"
  }
}
```

---

## Frontend Flow

### Onboarding Wizard (React/Vue/etc.)

**Step 1: Welcome Screen**
```
Welcome to [Clinic Name]!
Let's set up your profile so patients can book sessions with you.

You'll need:
✓ Calendly account (check your email for invitation)
✓ 3 event types created (30, 45, 60 minutes)
✓ Personal Access Token from Calendly

[Get Started] button
```

**Step 2: Calendly Setup**
```
Step 1 of 2: Connect Calendly

Before continuing, make sure you've:
1. Accepted the Calendly invitation
2. Created these event types:
   - 30-minute session
   - 45-minute session
   - 60-minute session
3. Added "Phone Number" field to each event type

Need help? [View Setup Guide]

Enter your Calendly Personal Access Token:
[Input field: PAT]
[How do I get this?] link

[Validate & Continue] button
```

On "Validate" click:
- Call `POST /therapist/onboarding/validate-calendly`
- Show spinner
- If valid: show success + preview
- If invalid: show error message
- If warnings: show warnings but allow continue

**Step 3: Specialties**
```
Step 2 of 2: Select Your Specialties

Which areas do you specialize in? (Select all that apply)

☐ Sports Rehabilitation
☐ Women's Health
☐ Pediatric Physiotherapy
☐ Orthopedic Rehabilitation
☐ Neurological Rehabilitation
☐ Geriatric Physiotherapy

[Back]  [Complete Setup]
```

On "Complete Setup" click:
- Call `POST /therapist/onboarding/complete` with PAT + specialty_ids
- Show spinner "Setting up your profile..."
- On success: redirect to dashboard
- On error: show error message

**Step 4: Success**
```
✅ Setup Complete!

Your profile is ready. Patients can now book sessions with you.

Your booking links:
- 30 min: https://calendly.com/sarah/30min
- 45 min: https://calendly.com/sarah/45min
- 60 min: https://calendly.com/sarah/60min

[Go to Dashboard]
```

---

## Security Considerations

1. **PAT Storage:**
   - DO NOT store the Calendly PAT in database
   - Only use it during onboarding API call
   - Discard immediately after use

2. **JWT Validation:**
   - All endpoints require valid JWT
   - Extract `user_id` from JWT
   - Therapist can only modify their own record

3. **Role Check:**
   - User must have `role = "therapist"` in JWT
   - Admins cannot use these endpoints (separate admin APIs)

4. **Rate Limiting:**
   - Limit onboarding attempts (prevent abuse of Calendly API)
   - Max 5 validation attempts per 10 minutes

---

## Database Changes

No schema changes needed! All models already support this:
- ✅ `Therapist.calendly_user_uri`
- ✅ `TherapistEventType` table
- ✅ `TherapistSpecialtyMap` table

---

## Implementation Files

| File | Purpose |
|------|---------|
| `app/api/v1/routes/therapist/onboarding.py` | New onboarding endpoints |
| `app/services/therapist_onboarding.py` | Business logic for onboarding |
| `app/core/auth.py` | Add `get_current_therapist()` helper |
| `tests/test_therapist_onboarding.py` | Tests for onboarding flow |

---

## Updated Onboarding Process

### Admin Steps (Minimal)
1. Add therapist to Calendly (invite sent)
2. Create User account in Neon Auth (or let therapist self-register)
3. Done! Therapist does the rest.

### Therapist Steps (Self-Service)
1. Accept Calendly invite
2. Create 3 event types (30/45/60 min)
3. Generate PAT in Calendly
4. Log into web UI
5. Complete onboarding wizard (paste PAT, select specialties)
6. Done! Profile is live.

---

## Benefits

✅ **Reduced admin workload** - No manual API calls or database updates
✅ **Faster onboarding** - Therapist can complete in 5 minutes
✅ **Self-service** - Therapist controls their profile
✅ **Error-proof** - Validation catches issues before saving
✅ **Re-syncable** - Therapist can update event types anytime
✅ **Secure** - PAT never stored, JWT-protected endpoints

---

## Open Questions

1. **What if therapist's Calendly email doesn't match Neon Auth email?**
   - Option A: Allow mismatch, store both
   - Option B: Require match, show error

2. **Should we allow therapist to change Calendly URI after onboarding?**
   - Probably no (would break existing sessions)
   - Admin-only override if needed

3. **What if therapist deletes an event type in Calendly?**
   - Re-sync detects it, marks `is_active = false`
   - Warn therapist in UI

4. **Should PAT validation be a separate step or combined with completion?**
   - Separate (better UX, shows preview)
   - Current design: separate validation endpoint
