# V1 Implementation Plan — Physio Booking System

Version: 1.1 | Date: 2026-02-09 | Status: In progress

## Context

The current codebase is a working prototype with a single-physio WhatsApp bot handling booking, payments, session notes, and admin approval — all via WhatsApp. The V1 spec requires a fundamental restructure:

- **WhatsApp bot** becomes customer-only with IVR-style numbered menus
- **Web UI REST APIs** handle all admin/therapist workflows (payments, receipts, notes, calendars)
- **Multi-therapist matching** replaces the single-physio model
- **Calendly webhooks** replace polling for booking confirmation
- **Separate User/Client tables**, renamed Session model, integer cents for money

This plan is broken into 6 phases, each producing a working (if incomplete) system. Each phase is a separate PR to `dev`.

---

## Architecture Decisions (Locked)

| Decision | Choice |
|----------|--------|
| WhatsApp bot | IVR-style numbered menus, customer booking only |
| Payments | All payment handling on web UI |
| Calendly sync | Webhooks (invitee.created/rescheduled/canceled) |
| Auth | Neon Auth (JWT) for web UI staff |
| Therapist data | Separate `Therapist` table linked to `User` |
| Specialties | Admin-managed CRUD |
| Calendly tokens | Design for both org-level and per-therapist |
| Returning users | Shortcut: "Book again with Dr. XYZ" |
| Physio/admin WhatsApp | Strip now |
| User vs Client | Split: `User` = staff, `Client` = WhatsApp customers |
| Naming | `Appointment` → `Session` |
| Money | Integer cents everywhere |
| Webhook security | Add after core flows |
| Message logs | Log from the start |
| Migration | Clean slate (drop and recreate) |
| Client name | Collected by bot on first interaction |

---

## Phase Dependency Graph

```
Phase 1 (Models + DB)                           ✅ PR #26
  ├──→ Phase 2 (Bot + Logging)                   ✅ PR #27
  │      └──→ Phase 2.5 (Admin APIs)             ✅ PR #28
  │             └──→ Phase 3.1 (Matching Engine)  ✅ PR pending
  │                    └──→ Phase 3.2 (Calendly Webhooks)  ← YOU ARE HERE
  │                           └──→ Phase 4 (Scheduler)
  │                                  └──→ Phase 5 (Web APIs - Complete)
  │                                         └──→ Phase 6 (Security + Auth)
  └──→ Phase 2.5 (can also start after Phase 1, parallel with Phase 2)
```

**Rationale for Phase 2.5**: Cannot test Phase 2 bot or build Phase 3 matching without therapist/specialty data in DB. Phase 2.5 provides minimal CRUD APIs to enable both.

**Rationale for Phase 3 split**: Matching engine (3.1) is not blocked by Calendly account setup. Calendly webhooks (3.2) require a Standard plan ($10/seat/mo) with Scheduling API + webhooks. Time-band scoring in the matching engine is deferred until 3.2 provides Calendly event type data.

---

## Phase 1: Data Model Foundation + Clean Slate DB ✅

**Branch**: `v1/phase-1-data-models` | **PR**: #26 (merged to dev)

### Goal
Replace all 4 existing models with the V1 schema. Wipe Alembic history. Produce a single fresh migration.

### New Models (all `app/models/`)

**`user.py`** — Staff users (therapists + admins), authenticated via Neon Auth:
```
User: id, neon_auth_sub (unique), email (unique), display_name, role (admin|therapist),
      is_active, created_at, updated_at
```

**`client.py`** — WhatsApp customers, identified by phone:
```
Client: id, phone_e164 (unique, indexed), name, conversation_state, conversation_data (JSON),
        preferred_therapist_id (FK→therapist), created_at, updated_at
```

**`therapist.py`** — Therapist profile, linked to User:
```
Therapist: id, user_id (FK→user, unique), display_name, is_active, calendly_user_uri, created_at
```

**`specialty.py`** — Admin-managed specialties + M2M:
```
TherapistSpecialty: id, name (unique), description, is_active
TherapistSpecialtyMap: id, therapist_id (FK), specialty_id (FK) — unique together
```

**`event_type.py`** — Calendly event type mapping per therapist:
```
TherapistEventType: id, therapist_id (FK), calendly_event_type_uri (unique),
                    duration_minutes, scheduling_url, is_active
```

**`session.py`** — Replaces Appointment:
```
Session: id, client_id (FK), therapist_id (FK), start_time, end_time, duration_minutes,
         status (scheduled|started|completed|cancelled|no_show),
         source (calendly|manual), charge_amount_cents, currency (HKD),
         calendly_event_uri (unique), calendly_invitee_uri,
         reminder_sent, therapist_notified, created_at, updated_at
```

**`session_note.py`** — Rewritten:
```
SessionNote: id, session_id (FK), author_user_id (FK→user), note_text (Text),
             is_read, created_at
```

**`matching.py`** — Audit trail for matching decisions:
```
MatchingDecision: id, client_id (FK), requested_duration, requested_specialty,
                  requested_time_band, requested_days (JSON), selected_therapist_id (FK),
                  scoring_breakdown (JSON), rationale, fallback_level, created_at
```

**`payment.py`** — Financial entities (all money in integer cents):
```
PaymentRecord: id, session_id (FK), amount_cents, currency, payment_method,
               status (pending|confirmed|rejected), recorded_by_user_id (FK), created_at, updated_at

PaymentProof: id, payment_record_id (FK), proof_url, uploaded_by_user_id (FK), created_at

Receipt: id, client_id (FK), session_id (FK, nullable), amount_cents, currency,
         description, pdf_url, status, issued_by_user_id (FK), created_at

ClientFinancial: id, client_id (FK, unique), total_paid_cents, total_receipted_cents,
                 currency, updated_at
```

**`message_log.py`** — WhatsApp message log:
```
MessageLog: id, direction (inbound|outbound), phone_e164 (indexed), body, media_url,
            twilio_sid, client_id (FK, nullable), created_at
```

### Actions

| Action | Files |
|--------|-------|
| Delete | `app/models/appointment.py`, all `alembic/versions/*`, `physio.db` |
| Rewrite | `app/models/user.py`, `app/models/payment.py`, `app/models/session_note.py` |
| Create | `app/models/client.py`, `therapist.py`, `specialty.py`, `event_type.py`, `session.py`, `matching.py`, `message_log.py` |
| Modify | `app/models/__init__.py` (export all 14 models), `app/core/config.py` (add webhook secrets, currency; remove admin/physio phone) |
| Stub | `app/tasks/process_whatsapp.py` (return stub), `app/main.py` (no-op scheduler), `app/api/v1/__init__.py` (disable session_notes route) |
| Generate | `alembic revision --autogenerate -m "v1_initial_schema"` |

### Verify
- `alembic upgrade head` succeeds on fresh DB
- `uvicorn app.main:app` starts without crash
- `GET /` returns health check
- All 14 tables exist with correct columns, FKs, indexes

---

## Phase 2: Message Logging + WhatsApp Bot Rewrite (IVR) ✅

**Branch**: `v1/phase-2-whatsapp-bot` | **PR**: #27 (merged to dev)

### Goal
Rewrite the WhatsApp bot as a customer-only IVR. Log all messages. Strip all physio/admin handlers.

### Bot Conversation Flow

**New client** (no name stored):
```
[Hi] → AWAITING_NAME: "Welcome! What's your name?"
     → AWAITING_DURATION: "Hi {name}! Choose session length: 1→30min, 2→45min, 3→60min"
     → AWAITING_SPECIALTY: "What do you need help with? 1→Sports Rehab, 2→..."
     → AWAITING_TIME_BAND: "Preferred time? 1→Morning (8-11), 2→Afternoon (11-4), 3→Evening (4-8)"
     → AWAITING_DAYS: "Which days work? 1→Mon, 2→Tue, ... (comma-separated)"
     → [matching engine runs]
     → AWAITING_MATCH_CONFIRM: "Matched Dr. XYZ (Sports Rehab). Reply 1 to book, 2 to try different preferences"
     → [1] → sends Calendly booking link, resets to IDLE
```

**Returning client** (has name + previous therapist):
```
[Hi] → AWAITING_REBOOK_CHOICE: "Hi {name}! Reply 1 to book again with Dr. XYZ, or 2 for new booking"
     → [1] → skip to AWAITING_DURATION (pre-fill specialty from last session)
     → [2] → full flow from AWAITING_DURATION
```

**At any step**: invalid input → re-prompt with the same menu.
**At any step**: "reschedule" or "cancel" → show Calendly links for upcoming sessions.

### New Files

| File | Purpose |
|------|---------|
| `app/services/bot/__init__.py` | Exports `process_message` |
| `app/services/bot/router.py` | Gets/creates Client, logs inbound, dispatches by `conversation_state` |
| `app/services/bot/states.py` | State constants: IDLE, AWAITING_NAME, AWAITING_DURATION, etc. |
| `app/services/bot/handlers.py` | One handler function per state, strict numbered-input validation |
| `app/services/bot/helpers.py` | `get_or_create_client`, `send_and_log`, `validate_numbered_choice`, conversation_data JSON helpers |
| `app/services/bot/menus.py` | Build menu text strings (duration, specialty, time band, days, rebook) |
| `app/services/bot/reschedule.py` | Reschedule/cancel — look up upcoming sessions, return Calendly links |
| `app/services/message_logger.py` | `log_inbound()`, `log_outbound()` → MessageLog table |
| `tests/conftest.py` | SQLite in-memory DB, session fixture, mock send_whatsapp_message |
| `tests/test_bot_handlers.py` | Unit tests per handler |
| `tests/test_bot_flow.py` | Integration: full conversation simulations |
| `tests/test_message_logging.py` | Logging tests |

### Modified Files

| File | Change |
|------|--------|
| `app/services/twilio_client.py` | Add optional `db`/`client_id` params for logging outbound messages |
| `app/tasks/process_whatsapp.py` | Import from `app.services.bot` instead of `app.bot_logic` |
| `requirements.txt` | Add `pytest`, `httpx` |

### Deleted Files

| File | Reason |
|------|--------|
| `app/bot_logic.py` | Replaced by `app/services/bot/` package |
| `test_scenarios.py` | Replaced by pytest tests |

### Key Design Decisions

**`conversation_data` as JSON string**: The multi-step IVR collects ~5 intermediate values (duration, specialty_id, time_band, days, matched_therapist_id). A single JSON blob avoids adding 5+ nullable columns to Client. `conversation_state` drives the state machine; `conversation_data` holds accumulated answers.

**Bot package instead of single file**: Current `bot_logic.py` at 716 lines is unwieldy. V1 bot has more states. Split into router/handlers/helpers/menus keeps each file ~100-150 lines and handlers independently testable.

### Verify
- `pytest tests/` all green
- Full new-client flow via `/api/v1/whatsapp/test`: hi → name → duration → specialty → time band → days → match result
- Returning client shortcut works
- Invalid input at every step gets re-prompt
- "reschedule" / "cancel" shows links
- All messages logged in `message_log` table
- No physio/admin handling anywhere in the bot

---

## Phase 2.5: Admin APIs (Therapist & Specialty Management) ✅

**Branch**: `v1/phase-2.5-admin-apis` | **PR**: #28 (merged to dev)

### Goal
Build minimal CRUD APIs for therapists and specialties to enable:
- Testing Phase 2 bot flow with real data
- Setting up Calendly links for Phase 3 integration
- Frontend therapist registration and management

**Note**: Auth middleware is intentionally deferred to Phase 6. Frontend sends JWT tokens, but endpoints remain open for now to prioritize feature delivery.

### Admin Endpoints (`app/api/v1/routes/admin/`)

#### Therapist Management

| Endpoint | Purpose | Request Body |
|----------|---------|--------------|
| `GET /admin/therapists` | List all therapists with specialties | — |
| `POST /admin/therapists` | Create therapist + user | `{neon_auth_sub, email, display_name, calendly_link}` |
| `GET /admin/therapists/{id}` | Get therapist detail | — |
| `PATCH /admin/therapists/{id}` | Update therapist | `{display_name?, is_active?, calendly_link?}` |
| `DELETE /admin/therapists/{id}` | Soft-delete (set `is_active=false`) | — |

#### Specialty Management

| Endpoint | Purpose | Request Body |
|----------|---------|--------------|
| `GET /admin/specialties` | List all specialties | — |
| `POST /admin/specialties` | Create specialty | `{name, description}` |
| `PATCH /admin/specialties/{id}` | Update specialty | `{name?, description?, is_active?}` |
| `DELETE /admin/specialties/{id}` | Soft-delete (set `is_active=false`) | — |

#### Therapist-Specialty Assignment

| Endpoint | Purpose | Request Body |
|----------|---------|--------------|
| `POST /admin/therapists/{id}/specialties` | Assign specialty to therapist | `{specialty_id}` |
| `DELETE /admin/therapists/{id}/specialties/{sid}` | Remove specialty from therapist | — |
| `GET /admin/therapists/{id}/specialties` | List therapist's specialties | — |

### Schemas (`app/api/v1/schemas/`)

**`therapist.py`**:
```python
class TherapistCreate(BaseModel):
    neon_auth_sub: str
    email: str
    display_name: str
    calendly_link: str | None = None

class TherapistUpdate(BaseModel):
    display_name: str | None = None
    is_active: bool | None = None
    calendly_link: str | None = None

class TherapistResponse(BaseModel):
    id: int
    user_id: int
    display_name: str
    is_active: bool
    calendly_link: str | None
    specialties: list[SpecialtyResponse]
    created_at: datetime
```

**`specialty.py`**:
```python
class SpecialtyCreate(BaseModel):
    name: str
    description: str | None = None

class SpecialtyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None

class SpecialtyResponse(BaseModel):
    id: int
    name: str
    description: str | None
    is_active: bool
```

### Implementation Notes

1. **User Creation**: `POST /admin/therapists` creates both `User` and `Therapist` records atomically
2. **Soft Deletes**: All DELETE endpoints set `is_active=false` instead of actual deletion
3. **Calendly Link**: Stored on `Therapist` model, validated as URL format (optional)
4. **Validation**:
   - Email uniqueness enforced at DB level
   - Specialty name uniqueness enforced
   - Cannot assign same specialty twice to therapist
5. **Response Format**: All endpoints return JSON with standard error handling:
   ```json
   {"status": "success", "data": {...}}
   {"status": "error", "message": "..."}
   ```

### New Files

| File | Purpose |
|------|---------|
| `app/api/v1/schemas/therapist.py` | Therapist request/response schemas |
| `app/api/v1/schemas/specialty.py` | Specialty request/response schemas |
| `app/api/v1/routes/admin/therapists.py` | Therapist CRUD endpoints |
| `app/api/v1/routes/admin/specialties.py` | Specialty CRUD endpoints |
| `tests/test_admin_therapists.py` | Therapist API tests |
| `tests/test_admin_specialties.py` | Specialty API tests |

### Modified Files

| File | Change |
|------|--------|
| `app/api/v1/__init__.py` | Register admin router |
| `app/main.py` | Include admin routes |

### Verify

- ✅ Can create therapist with Calendly link
- ✅ Can create and assign specialties
- ✅ Soft delete works (is_active=false)
- ✅ GET /admin/therapists returns therapists with specialties
- ✅ Duplicate email/specialty name blocked
- ✅ Can test Phase 2 bot flow with real therapists
- ✅ All endpoints return proper JSON responses
- ✅ pytest passes for admin API tests

### Auth Implementation (Deferred to Phase 6)

Frontend in `../physio-whatsapp-frontend` handles authentication via Neon Auth and sends JWT tokens with requests. Backend will validate these tokens in Phase 6 using:

```python
# Phase 6: Add JWT middleware
from app.core.auth import require_admin

@router.post("/admin/therapists", dependencies=[Depends(require_admin)])
async def create_therapist(...):
    ...
```

For Phase 2.5, endpoints remain open to enable rapid testing and frontend integration.

---

## Phase 3: Matching Engine + Calendly Webhooks

Split into two sub-phases since Calendly webhooks require account setup.

### Phase 3.1: Matching Engine ✅

**Branch**: `v1/phase-3-matching` | **PR**: pending

#### Goal
Implement the 4-factor scoring matching engine. Connect matching to the bot. Replaces the stub that picked the first active therapist.

#### Matching Engine (`app/services/matching.py`)

**Scoring weights (higher is better)**:
1. **Specialty match** (100 pts) — therapist has requested specialty
2. **Continuity bonus** (30 pts) — therapist is client's `preferred_therapist_id`
3. **Time-band match** (10 pts) — deferred until Calendly integration (always scores 0, shows `time_band_match: null` in breakdown)
4. **Lower load** (0-9 pts) — fewer sessions in next 7 days (tie-breaker)

Weight separations ensure priority: specialty (100) always beats continuity+time+load (30+10+9=49).

**Fallback cascade**:
- Level 0: specialty + time-band match (collapses with Level 1 while time-band deferred)
- Level 1: specialty only
- Level 2: time-band only (collapses with Level 3 while time-band deferred)
- Level 3: any active therapist (lowest load wins)

**Deterministic tie-breaking**: lower therapist ID wins when scores are equal.

**Exclude therapist**: `exclude_therapist_id` parameter filters a therapist from the candidate pool entirely. Used when client picks "Book with a different therapist" — the preferred therapist is excluded (not just ignored), while `preferred_therapist_id` is preserved for future bookings.

**Audit**: Every `match_therapist()` call persists a `MatchingDecision` row with full per-therapist scoring breakdown, rationale, and fallback level — even when no match is found.

**Output**: `MatchResult` dataclass → `therapist`, `rationale`, `fallback_level`, `scoring_breakdown`

#### Bot Connection
- `handle_awaiting_days` calls `match_therapist()` with specialty, duration, days, preferred/excluded therapist
- "Rebook with same therapist" (choice 1) → bypasses matching, uses `preferred_therapist_id` directly
- "Book with different therapist" (choice 2) → stores `exclude_therapist_id` in conversation_data, runs matching with preferred therapist excluded
- "Book" keyword → runs matching normally, preferred therapist gets continuity bonus

#### New Files

| File | Purpose |
|------|---------|
| `app/services/matching.py` | 4-factor scoring engine with fallback cascade |
| `tests/test_matching.py` | 34 tests: scoring, fallback, audit trail, exclude, determinism |

#### Verify
- ✅ Matching returns correct therapist for various input combinations
- ✅ Fallback cascade works (levels 0-3, collapsing while time-band deferred)
- ✅ `matching_decision` rows appear in DB with per-therapist scoring breakdown
- ✅ Continuity bonus applied when client has `preferred_therapist_id`
- ✅ Excluded therapist never matched or shown in breakdown
- ✅ 181 tests passing (34 matching + 147 existing)

---

### Phase 3.2: Calendly Webhooks

**Branch**: `v1/phase-3.2-calendly-webhooks` (planned)

#### Goal
Add Calendly webhook receiver and scheduling URL generation. Requires Calendly Standard plan account setup.

#### Calendly Webhook (`app/api/v1/routes/calendly_webhook.py`)

`POST /api/v1/webhooks/calendly` handles:
- **invitee.created** → create Session (link to Client by invitee info, link to Therapist by event_type_uri → TherapistEventType)
- **invitee.rescheduled** → update Session start_time/end_time
- **invitee.canceled** → set Session status = "cancelled"
- Idempotency via unique `calendly_event_uri`
- No signature verification yet (Phase 6)

#### Calendly Service Changes (`app/services/calendly.py`)

| Keep | Remove | Add |
|------|--------|-----|
| `get_event_types()` | `check_availability()` | `get_scheduling_url(therapist_id, duration, db)` |
| `get_event_link()` | (polling logic) | `parse_webhook_payload(payload) → CalendlyEvent` |
| | | `get_calendly_headers(therapist)` — supports org or per-therapist tokens |

#### Bot Connection
- `handle_awaiting_match_confirm` calls `get_scheduling_url()` → sends Calendly link
- Bot never creates Session records — Calendly webhook does that
- Time-band scoring (10 pts) can be enabled once Calendly event types are queryable

#### New Files

| File | Purpose |
|------|---------|
| `app/api/v1/routes/calendly_webhook.py` | Webhook receiver |
| `tests/test_calendly_webhook.py` | Webhook create/reschedule/cancel tests |

#### Verify
- Calendly webhook creates/updates/cancels Sessions
- Full bot flow sends real Calendly scheduling links
- Time-band scoring enabled (if Calendly data available)

---

## Phase 4: Scheduler Update + Session Lifecycle

**Branch**: `v1/phase-4-scheduler-lifecycle`

### Goal
Rewrite APScheduler reminders for the new Session/Client/Therapist models. Handle session lifecycle.

### Scheduler Rewrite (`app/main.py`)

`send_scheduled_reminders()` now:
- Queries `Session` (not Appointment) for upcoming sessions
- Looks up `Client.phone_e164` for reminders
- Auto-completes sessions past `end_time` that are still "started"
- **Removed**: all physio payment flow triggers, physio notifications via WhatsApp

### Session Lifecycle Service (`app/services/session_lifecycle.py`)

- `complete_session(db, session_id)` — mark completed
- `cancel_session(db, session_id)` — mark cancelled
- `get_upcoming_sessions(db, client_id)` — for reschedule/cancel in bot
- `get_therapist_sessions(db, therapist_id, start, end)` — for web UI calendar

### New Files

| File | Purpose |
|------|---------|
| `app/services/session_lifecycle.py` | Session lifecycle helpers |
| `tests/test_scheduler.py` | Reminder + auto-completion tests |
| `tests/test_session_lifecycle.py` | Lifecycle helper tests |

### Verify
- Scheduler sends reminders for sessions within 30 min
- Reminders not re-sent
- Sessions auto-complete after end_time
- No payment flow in scheduler

---

## Phase 5: Web UI REST APIs (Admin + Therapist)

**Branch**: `v1/phase-5-web-api`

### Goal
Build authenticated REST APIs for the Web UI. This is the largest phase (~20 endpoints) but follows uniform CRUD patterns.

### Auth Enhancement (`app/core/auth.py`)

- `get_current_user` returns `User` model (lookup by `neon_auth_sub`)
- `require_role(*roles)` — dependency factory for role gating
- `get_current_therapist` — gets current user's Therapist record

### Admin Endpoints (`app/api/v1/routes/admin/`)

| Endpoint | Purpose |
|----------|---------|
| `GET /admin/therapists` | List all therapists with specialties |
| `POST /admin/therapists` | Create therapist |
| `PATCH /admin/therapists/{id}` | Update therapist |
| `POST /admin/therapists/{id}/specialties` | Add specialty mapping |
| `DELETE /admin/therapists/{id}/specialties/{sid}` | Remove specialty |
| `POST /admin/therapists/{id}/event-types` | Add Calendly event type |
| `GET/POST /admin/specialties` | Specialty CRUD |
| `PATCH /admin/specialties/{id}` | Update specialty |
| `GET /admin/sessions` | List sessions (filters: therapist, client, date, status) |
| `POST /admin/sessions` | Create manual session (source="manual") |
| `PATCH /admin/sessions/{id}` | Update session status |
| `GET /admin/payments` | List payment records |
| `PATCH /admin/payments/{id}` | Confirm/reject payment |
| `GET /admin/receipts` | List receipts |
| `POST /admin/receipts` | **Create receipt (balance enforced)** |
| `GET /admin/clients` | List clients |
| `GET /admin/clients/{id}` | Client detail + financials |
| `GET /admin/clients/{id}/messages` | Message history |
| `GET /admin/clients/{id}/financials` | Financial record |

### Therapist Endpoints (`app/api/v1/routes/therapist/`)

| Endpoint | Purpose |
|----------|---------|
| `GET /therapist/sessions` | Own sessions (scoped by auth) |
| `GET /therapist/sessions/{id}` | Session detail (must own) |
| `POST /therapist/sessions/{id}/payment` | Record payment received |
| `POST /therapist/payments/{id}/proof` | Upload payment proof |
| `GET /therapist/sessions/{id}/notes` | List session notes |
| `POST /therapist/sessions/{id}/notes` | Create note |
| `PATCH /therapist/notes/{id}` | Update own note |
| `DELETE /therapist/notes/{id}` | Delete own note |

### Financial Balance Service (`app/services/financials.py`)

- `record_payment(db, session_id, amount_cents, method, user_id)` → creates PaymentRecord, updates ClientFinancial.total_paid_cents
- `issue_receipt(db, client_id, amount_cents, user_id)` → **blocks if amount > (total_paid - total_receipted)**, updates ClientFinancial.total_receipted_cents
- `get_client_balance(db, client_id)` → returns total_paid, total_receipted, available

### Schemas (`app/api/v1/schemas/`)

One schema file per entity: `therapist.py`, `specialty.py`, `session.py`, `session_note.py`, `payment.py`, `receipt.py`, `client.py`, `message_log.py`

### New Files

| File | Purpose |
|------|---------|
| `app/api/v1/schemas/*` | 8 schema files |
| `app/api/v1/routes/admin/*` | 6 admin route files |
| `app/api/v1/routes/therapist/*` | 3 therapist route files |
| `app/services/financials.py` | Balance enforcement |
| `tests/test_admin_api.py` | Admin endpoint tests |
| `tests/test_therapist_api.py` | Therapist endpoint tests |
| `tests/test_financials.py` | Balance enforcement tests |
| `tests/test_auth.py` | Role-based access tests |

### Deleted
- `app/api/v1/routes/session_notes.py` (replaced by `therapist/notes.py`)

### Verify
- All endpoints respond with correct auth
- Therapist cannot access admin routes
- Receipt blocked when amount > available balance
- Payment recording updates ClientFinancial
- Manual session creation works

---

## Phase 6: Security Hardening + Final Polish

**Branch**: `v1/phase-6-security-polish`

### Goal
Add webhook signature verification, tighten CORS, clean up debug mode, update docs.

### Webhook Security (`app/core/webhook_security.py`)

- `require_twilio_signature` — FastAPI dependency, uses `twilio.request_validator.RequestValidator`
- `require_calendly_signature` — FastAPI dependency, HMAC verification
- Applied to `/api/v1/whatsapp` and `/api/v1/webhooks/calendly`

### Other Changes
- CORS: read `allowed_origins` from config instead of `["*"]`
- `/api/v1/whatsapp/test` returns 404 when `debug_mode=False`
- Convert `print()` statements to proper `logging`
- Update `README.md`, `docs/project-structure.md`, `.env.example`
- Create `docs/api-guide.md`

### Verify
- Unsigned webhooks rejected (403)
- Test endpoint hidden in production
- CORS only allows configured origins
- Full test suite green

---

## Final V1 File Tree (New/Changed)

```
app/
  core/
    auth.py                          [MODIFIED - role deps]
    config.py                        [MODIFIED - new settings]
    webhook_security.py              [NEW]
  models/
    __init__.py                      [MODIFIED - 14 model exports]
    user.py                          [REWRITTEN - staff only]
    client.py                        [NEW]
    therapist.py                     [NEW]
    specialty.py                     [NEW]
    event_type.py                    [NEW]
    session.py                       [NEW - replaces appointment.py]
    session_note.py                  [REWRITTEN]
    payment.py                       [REWRITTEN - 4 classes]
    matching.py                      [NEW]
    message_log.py                   [NEW]
  services/
    bot/
      __init__.py, router.py, states.py, handlers.py,
      helpers.py, menus.py, reschedule.py    [ALL NEW - replaces bot_logic.py]
    calendly.py                      [MODIFIED - webhooks, multi-therapist]
    twilio_client.py                 [MODIFIED - logging hook]
    message_logger.py                [NEW]
    matching.py                      [NEW]
    session_lifecycle.py             [NEW]
    financials.py                    [NEW]
  api/v1/
    __init__.py                      [MODIFIED]
    schemas/ (8 files)               [ALL NEW]
    routes/
      whatsapp.py                    [MODIFIED]
      calendly_webhook.py            [NEW]
      admin/ (6 files)               [ALL NEW]
      therapist/ (3 files)           [ALL NEW]
  tasks/
    process_whatsapp.py              [MODIFIED]
  main.py                           [MODIFIED]
tests/
  conftest.py + 14 test files        [ALL NEW]
docs/
  v1-implementation-plan.md          [THIS FILE]
  api-guide.md                       [NEW in Phase 6]
```

### Deleted Files
- `app/bot_logic.py`, `app/models/appointment.py`, `test_scenarios.py`
- All existing `alembic/versions/*`, `physio.db`
