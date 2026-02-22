# Backend Bind Sheet - Phase B Freeze (2026-02-22)

## Scope
This file is the backend source of truth for FE integration on Phase B.

- OpenAPI snapshot: `docs/contracts/openapi-v1-2026-02-22-phaseB-implemented.json`
- Base path: `/api/v1`

## 1) Generate Invoice
`POST /api/v1/admin/invoices/generate`

### Request
Required:
- `client_id: int`
- `currency: str`
- `description: str`

Optional:
- `session_id: int | null`
- `therapist_id: int | null`
- `service_type: "standard" | "supervised_physio" | "other"` (default `"standard"`)
- `trainer_name: str | null`
- `reference_note: str | null`
- `amount_cents: int | null`
- `payment_mode: str | null`
- `diagnosis: str | null`
- `special_notes: str | null`

### Behavior
- Session-linked: include `session_id`.
- Sessionless: omit `session_id` or send `null`.
- Amount precedence:
1. If `amount_cents` provided, backend uses it.
2. If omitted and `session_id` present, backend tries expected charge fallback.
3. If no amount resolves, backend returns `400 amount_cents_required`.
- Financial guard is strict across client totals.

### Known Error Codes
- `400 amount_exceeds_available_to_receipt`
- `400 amount_cents_required`
- `400 therapist_session_mismatch`
- `400 invalid_service_type`
- `404 client_not_found`
- `404 session_not_found`
- `404 therapist_not_found`

## 2) Client Receipting Summary
`GET /api/v1/admin/clients/{client_id}/receipting/summary?limit=20&offset=0`

### Response
- `client_id`
- `currency`
- `total_paid_cents`
- `total_receipted_cents`
- `claimable_balance_cents`
- `receipts[]` (paginated receipt ledger)
- `limit`, `offset`, `has_more`

## 3) Therapist Invoice Views
- `GET /api/v1/therapist/invoices`
- `GET /api/v1/therapist/invoices/{invoice_id}`

Notes:
- Scoping now uses `receipt.therapist_id`.
- Response includes `therapist_id`, `service_type`, `trainer_name`, `reference_note`.

## 4) Integration Guardrails

### WhatsApp webhook path
- Live endpoint: `POST /api/v1/whatsapp`
- Invalid legacy path: `POST /whatsapp` (will return 404)

### Therapist profile/timezone
- Live now: `GET /api/v1/therapist/me`
- Not live yet: `PUT/PATCH /api/v1/therapist/me` for `preferred_timezone`
- `preferred_timezone` is not yet in current backend model/contracts.

### Therapist session status mutation
- Live endpoint: `PATCH /api/v1/therapist/sessions/{session_id}/status`
- Allowed `status`: `scheduled | started | completed | cancelled | no_show`

## 5) Quick Endpoint Matrix
Implemented and safe to bind:
- `POST /api/v1/admin/invoices/generate`
- `GET /api/v1/admin/clients/{client_id}/receipting/summary`
- `GET /api/v1/admin/sessions`
- `GET /api/v1/therapist/invoices`
- `GET /api/v1/therapist/invoices/{invoice_id}`
- `PATCH /api/v1/therapist/sessions/{session_id}/status`
- `POST /api/v1/whatsapp`

Not implemented / do not bind yet:
- `POST /whatsapp` (legacy wrong path)
- `PUT/PATCH /api/v1/therapist/me` for timezone persistence
