# Backend Bind Sheet - Admin Timezone Parity (2026-02-22)

## Scope
This sheet unblocks FE `/admin/settings` timezone persistence.

- OpenAPI snapshot: `docs/contracts/openapi-v1-2026-02-22-admin-timezone-parity.json`
- Base path: `/api/v1`

## 1) Read Admin Preferred Timezone
`GET /api/v1/admin/me/timezone`

### Success response
```json
{
  "preferred_timezone": "Asia/Hong_Kong"
}
```

- If admin timezone has never been set, response is:
```json
{
  "preferred_timezone": null
}
```

## 2) Persist Admin Preferred Timezone
`PATCH /api/v1/admin/me/timezone`

### Request
```json
{
  "preferred_timezone": "Asia/Hong_Kong"
}
```

- `preferred_timezone` must be a valid IANA timezone identifier.
- Input is trimmed server-side and normalized to canonical IANA key.

### Success response
```json
{
  "preferred_timezone": "Asia/Hong_Kong",
  "message": "Preferred timezone updated successfully"
}
```

### Validation / Errors
- `400 invalid_preferred_timezone` when timezone value is invalid.
- `401 invalid_token` when auth token missing/invalid.
- `403 access_denied` when caller is not an admin.

## 3) FE Integration flow
1. Call `GET /api/v1/admin/me/timezone`.
2. If `preferred_timezone` is null, detect device timezone and call `PATCH /api/v1/admin/me/timezone`.
3. Render admin dates/times using explicit stored timezone after persistence.
