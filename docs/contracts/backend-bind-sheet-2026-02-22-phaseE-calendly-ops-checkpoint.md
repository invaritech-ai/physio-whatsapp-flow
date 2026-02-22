# Backend Bind Sheet — Phase E Calendly Ops Checkpoint (2026-02-22)

## Status
- Backend Phase E queue/feed slice is implemented on `dev`.
- OpenAPI snapshot: `docs/contracts/openapi-v1-2026-02-22-phaseE-calendly-ops.json`

## New Endpoints
- `GET /api/v1/admin/calendly/queue`
- `POST /api/v1/admin/calendly/queue/{item_id}/ack`
- `POST /api/v1/admin/calendly/queue/{item_id}/resolve`
- `GET /api/v1/therapist/calendly/feed`
- `PATCH /api/v1/therapist/calendly/feed/{item_id}/seen`

## Event Types
- Admin queue `event_type`: `invitee.created | invitee.canceled | invitee.rescheduled`
- Therapist feed `event_type`: `created | canceled | rescheduled`

## Status Flows
- Queue status: `new -> acknowledged -> resolved`
- Feed status: `new -> seen`

## Webhook Integration Behavior
- `invitee.created` appends:
  - `admin.calendly.queue.invitee.created`
  - `therapist.calendly.feed.created`
- `invitee.canceled` appends:
  - `admin.calendly.queue.invitee.canceled`
  - `therapist.calendly.feed.canceled`
- `invitee.rescheduled` appends:
  - `admin.calendly.queue.invitee.rescheduled`
  - `therapist.calendly.feed.rescheduled`
- Reschedule signals received via `invitee.created` with old refs are normalized to the `rescheduled` queue/feed event.

## Idempotency
- Operational queue/feed writes dedupe by reason key:
  - `session:{session_id}:calendly:{created|canceled|rescheduled}`

## Verification
- Tests: `tests/test_phase_e_calendly_ops.py`
- Smoke run:
  - `uv run pytest -q tests/test_phase_e_calendly_ops.py tests/test_booking_notifications.py tests/test_calendly_webhooks_rescheduled.py`
