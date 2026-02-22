# Backend Bind Sheet - Timezone Write Path (2026-02-22)

## Scope
This sheet unblocks FE timezone persistence integration.

- OpenAPI snapshot: `docs/contracts/openapi-v1-2026-02-22-timezone-writepath.json`
- Base path: `/api/v1`

## 1) Read Therapist Profile
`GET /api/v1/therapist/me`

### Response update
`TherapistProfileResponse` now includes:
- `preferred_timezone: string | null`

If timezone has never been set, this field is `null`.

## 2) Persist Preferred Timezone
`PATCH /api/v1/therapist/me/timezone`

### Request
```json
{
  "preferred_timezone": "Asia/Hong_Kong"
}
```

- `preferred_timezone` must be a valid IANA timezone identifier.
- Input is trimmed server-side.

### Success response
```json
{
  "preferred_timezone": "Asia/Hong_Kong",
  "message": "Preferred timezone updated successfully"
}
```

### Validation / Errors
- `400 invalid_preferred_timezone` if timezone is not a valid IANA identifier.
- `401 invalid_token` if auth token is missing/invalid.
- `403 access_denied` for non-therapist role.

## 3) Legacy/Unsupported paths
- `PATCH /api/v1/therapist/onboarding/profile` does **not** accept timezone writes.
- Do not use this path for timezone persistence.

## 4) FE Integration flow
1. Call `GET /api/v1/therapist/me`.
2. If `preferred_timezone` is null, detect browser IANA timezone and call `PATCH /api/v1/therapist/me/timezone`.
3. Continue rendering with explicit timezone from profile, with local fallback only when null.
