# Backend Bind Sheet - Phase C Release Checkpoint (2026-02-22 17:15 HKT)

## Scope
Release-window backend source of truth for FE integration.

- OpenAPI snapshot: `docs/contracts/openapi-v1-2026-02-22-phaseC-release-checkpoint.json`
- Base path: `/api/v1`

## 1) Therapist Session Status Mutation Contract
Endpoint:
- `PATCH /api/v1/therapist/sessions/{session_id}/status`

Request:
- `status: "scheduled" | "started" | "completed" | "cancelled" | "no_show"`

Response is intentionally partial:
- `session_id`
- `status`
- `updated_at`

Important:
- This endpoint does **not** return full `SessionDetail`.
- FE should merge mutation response into existing state, or refetch:
  - `GET /api/v1/therapist/sessions/{session_id}`

## 2) Therapist In-App Notifications (New)
Endpoint:
- `GET /api/v1/therapist/notifications?limit=20&offset=0`

Response envelope:
- `items[]`
- `total`
- `limit`
- `offset`
- `has_more`

Current booking event type:
- `therapist.notification.booking_confirmed`

## 3) WhatsApp Booking Flow (Deterministic Update)
Key flow updates:
- first-time client: official HKID name capture
- menu now includes `Book therapist by name` for all clients
- duration options: `30` or `45` only
- time preference buckets:
  - `weekday day` (9am-5pm)
  - `weekday evening` (5pm onwards)
  - `weekend`

No LLM pathing introduced.

## 4) Async Booking Follow-up (Backend Internal)
When booking link is sent:
- follow-up nudge at `+1h` if still not booked
- follow-up nudge at `+6h` if still not booked

Controlled by env:
- `CELERY_BOOKING_FOLLOWUP_ENABLED`
- `BOOKING_FOLLOWUP_FIRST_DELAY_SECONDS`
- `BOOKING_FOLLOWUP_SECOND_DELAY_SECONDS`

## 5) MVP Release Burn-down (Remaining Steps)
1. FE consumes this bind sheet + confirms no contract ambiguity.
2. Joint FE+BE UAT pass on:
   - WhatsApp booking/rebook/cancel paths
   - Calendly create/cancel/reschedule sync
   - therapist status update + modal stability
   - admin invoice + receipting guardrails
3. Fix only release-blocking defects (no new scope).
4. Staging smoke + env parity check (`API`, `worker`, `beat`, `Redis`, webhook secrets).
5. Release candidate sign-off.
6. Production deploy + post-deploy smoke.

