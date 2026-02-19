# Patient + Billing API Draft (Backend v0.3)

Date: 2026-02-19  
Status: Draft with Phase 4/4.1 contract updates (2026-02-19)  
Owners: Backend Team + Frontend Team

## 1) Scope

This draft defines the proposed API contract for:

1. Admin patient management (maps to `Client` model)
2. Billing/invoice management (maps to `Receipt` + `ClientFinancial` + `PaymentRecord`)
3. Therapist invoice visibility

The endpoints below are proposed for contract freeze before implementation.

## 1.1 Contract Freeze Decisions (2026-02-19)

Agreed with frontend:

1. Invoice generation in v1 is single-session only.
2. Receipt guard is mandatory:
   - Sum of issued invoice amounts must not exceed `available_to_receipt_cents`.
3. Therapist invoice list/detail can include full client name + full phone (no masking in v1).
4. Client profile adds optional fields:
   - `email`
   - `date_of_birth`
   - `address`
5. `GET /api/v1/admin/clients` uses a paginated envelope:
   - `items`, `total`, `limit`, `offset`, `has_more`
6. Therapist `license_number` is required before onboarding completion and is exposed in therapist profile/admin therapist surfaces.
7. Invoice generation supports optional metadata fields:
   - `payment_mode`
   - `diagnosis` (override supported)
   - `special_notes`

## 2) Auth + Response Conventions

- All endpoints below require `Authorization: Bearer <token>`.
- Admin routes require `role=admin`.
- Therapist routes require `role=therapist`.
- Response style stays as raw object/list by default (no global `{status,data}` envelope in this phase).
- Exception: `GET /api/v1/admin/clients` returns a paginated metadata envelope.
- Validation/auth errors use existing backend patterns:
  - `401 invalid_token`
  - `403 access_pending`
  - `403 access_denied`
  - `403 account_inactive`

## 3) Patient API (Admin)

### 3.1 List/Search Patients

`GET /api/v1/admin/clients`

Query params:
- `q` (optional): name/phone contains search
- `phone_e164` (optional): exact phone lookup
- `email` (optional): exact or contains (implementation-defined, documented in OpenAPI)
- `date_of_birth` (optional): exact date (`YYYY-MM-DD`)
- `preferred_therapist_id` (optional)
- `limit` (default 50, max 200)
- `offset` (default 0)

Response:
```json
{
  "items": [
    {
      "id": 101,
      "name": "John Chan",
      "phone_e164": "+85291234567",
      "email": "john.chan@example.com",
      "date_of_birth": "1992-07-19",
      "address": "Flat 12A, Example Building, Kowloon, Hong Kong",
      "preferred_therapist_id": 12,
      "created_at": "2026-02-10T09:00:00Z",
      "updated_at": "2026-02-18T16:20:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

### 3.2 Create Patient

`POST /api/v1/admin/clients`

Request:
```json
{
  "name": "John Chan",
  "phone_e164": "+85291234567",
  "email": "john.chan@example.com",
  "date_of_birth": "1992-07-19",
  "address": "Flat 12A, Example Building, Kowloon, Hong Kong",
  "preferred_therapist_id": 12
}
```

Response:
```json
{
  "id": 101,
  "name": "John Chan",
  "phone_e164": "+85291234567",
  "email": "john.chan@example.com",
  "date_of_birth": "1992-07-19",
  "address": "Flat 12A, Example Building, Kowloon, Hong Kong",
  "preferred_therapist_id": 12,
  "created_at": "2026-02-19T12:00:00Z",
  "updated_at": "2026-02-19T12:00:00Z"
}
```

Notes:
- `phone_e164` must be valid E.164 and unique.
- `email`, `date_of_birth`, and `address` are optional.
- `date_of_birth` format: `YYYY-MM-DD`.

### 3.3 Get Patient Detail

`GET /api/v1/admin/clients/{client_id}`

Response:
```json
{
  "id": 101,
  "name": "John Chan",
  "phone_e164": "+85291234567",
  "email": "john.chan@example.com",
  "date_of_birth": "1992-07-19",
  "address": "Flat 12A, Example Building, Kowloon, Hong Kong",
  "preferred_therapist_id": 12,
  "created_at": "2026-02-10T09:00:00Z",
  "updated_at": "2026-02-18T16:20:00Z"
}
```

### 3.4 Update Patient

`PATCH /api/v1/admin/clients/{client_id}`

Request (all optional):
```json
{
  "name": "John C.",
  "phone_e164": "+85295555555",
  "email": "john.c@example.com",
  "date_of_birth": "1992-07-19",
  "address": "Unit 5, New Address, Hong Kong",
  "preferred_therapist_id": null
}
```

### 3.5 Patient Sessions

`GET /api/v1/admin/clients/{client_id}/sessions`

Query params:
- `status` (optional)
- `from` (optional ISO datetime)
- `to` (optional ISO datetime)
- `limit`, `offset`

Response:
```json
[
  {
    "id": 501,
    "therapist_id": 12,
    "start_time": "2026-02-21T03:00:00Z",
    "end_time": "2026-02-21T03:45:00Z",
    "duration_minutes": 45,
    "status": "scheduled",
    "source": "calendly",
    "charge_amount_cents": 65000,
    "currency": "HKD"
  }
]
```

### 3.6 Patient Message History

`GET /api/v1/admin/clients/{client_id}/messages`

Query params:
- `direction` (optional: `inbound|outbound`)
- `limit`, `offset`

Response:
```json
[
  {
    "id": 9001,
    "direction": "inbound",
    "phone_e164": "+85291234567",
    "body": "book",
    "media_url": null,
    "twilio_sid": "SMxxxxxxxx",
    "created_at": "2026-02-19T11:30:00Z"
  }
]
```

### 3.7 Patient Financial Summary

`GET /api/v1/admin/clients/{client_id}/financials`

Response:
```json
{
  "client_id": 101,
  "currency": "HKD",
  "total_paid_cents": 120000,
  "total_receipted_cents": 90000,
  "available_to_receipt_cents": 30000,
  "updated_at": "2026-02-19T10:00:00Z"
}
```

## 4) Billing/Invoice API (Admin)

Note: API uses `invoice` naming for frontend clarity. Storage maps to `Receipt`.

### 4.1 List Invoices

`GET /api/v1/admin/invoices`

Query params:
- `client_id` (optional)
- `therapist_id` (optional, via session join)
- `status` (optional: `pending|issued|voided`)
- `from` (optional ISO datetime)
- `to` (optional ISO datetime)
- `limit`, `offset`

Response:
```json
[
  {
    "id": 3001,
    "client_id": 101,
    "session_id": 501,
    "amount_cents": 65000,
    "currency": "HKD",
    "description": "Physio session invoice",
    "pdf_url": "https://s3.example.com/invoices/3001.pdf",
    "status": "issued",
    "created_at": "2026-02-19T12:10:00Z"
  }
]
```

### 4.2 Generate Invoice (PDF + S3)

`POST /api/v1/admin/invoices/generate`

Request:
```json
{
  "client_id": 101,
  "session_id": 501,
  "amount_cents": 65000,
  "currency": "HKD",
  "description": "Physio session invoice",
  "payment_mode": "cash",
  "diagnosis": "Bilateral plantar fasciitis",
  "special_notes": "Please submit to insurer within 30 days."
}
```

Behavior:
- Creates invoice record (`Receipt`) for one session only
- Generates PDF
- Uploads PDF to S3
- Saves `pdf_url`
- Enforces guard:
  - `amount_cents <= available_to_receipt_cents` at issuance time
- Metadata fallback precedence:
  - `payment_mode`: request > latest payment record > `"N/A"`
  - `diagnosis`: request > latest session note extraction > `"-"`
  - `special_notes`: request > `"-"`

Response:
```json
{
  "id": 3001,
  "client_id": 101,
  "session_id": 501,
  "amount_cents": 65000,
  "currency": "HKD",
  "description": "Physio session invoice",
  "pdf_url": "https://s3.example.com/invoices/3001.pdf",
  "status": "issued",
  "created_at": "2026-02-19T12:10:00Z"
}
```

### 4.3 Get Invoice Detail

`GET /api/v1/admin/invoices/{invoice_id}`

Response:
```json
{
  "id": 3001,
  "client_id": 101,
  "session_id": 501,
  "amount_cents": 65000,
  "currency": "HKD",
  "description": "Physio session invoice",
  "pdf_url": "https://s3.example.com/invoices/3001.pdf",
  "status": "issued",
  "issued_by_user_id": 1,
  "created_at": "2026-02-19T12:10:00Z"
}
```

## 5) Therapist Invoice API

### 5.1 List Therapist Invoices

`GET /api/v1/therapist/invoices`

Query params:
- `status` (optional)
- `from` (optional ISO datetime)
- `to` (optional ISO datetime)
- `limit`, `offset`

Returns invoices related to sessions owned by current therapist.

List/detail includes full client name and full phone for v1.

### 5.2 Get Therapist Invoice Detail

`GET /api/v1/therapist/invoices/{invoice_id}`

Ownership check required: therapist can only access invoices for their own sessions.

## 6) Error Contract (Endpoint-Level)

Recommended business-level errors:
- `400 invalid_phone_e164`
- `400 duplicate_phone_e164`
- `400 invalid_email`
- `400 invalid_date_of_birth`
- `400 invalid_amount_cents`
- `400 amount_exceeds_available_to_receipt`
- `404 client_not_found`
- `404 invoice_not_found`
- `409 invoice_generation_conflict`
- `422 validation_error`
- `500 invoice_pdf_generation_failed`
- `500 invoice_upload_failed`

## 7) Delivery Sequence (Proposed)

### Phase A (M2 support: Booking reliability)
1. `GET/POST/PATCH /api/v1/admin/clients`
2. `GET /api/v1/admin/clients/{id}`
3. `GET /api/v1/admin/clients/{id}/sessions`
4. `GET /api/v1/admin/clients/{id}/messages`
5. `GET /api/v1/admin/clients/{id}/financials`

### Phase B (M3 support: Billing MVP)
1. `GET /api/v1/admin/invoices`
2. `POST /api/v1/admin/invoices/generate`
3. `GET /api/v1/admin/invoices/{id}`
4. `GET /api/v1/therapist/invoices`
5. `GET /api/v1/therapist/invoices/{id}`

After each phase, regenerate OpenAPI contract snapshot.

## 8) Open Questions Before Implementation

1. Pagination style:
   - keep `limit/offset` only, or include `next_cursor` for frontend convenience?
2. Export requirements:
   - do we need CSV export endpoints in this phase or defer?
