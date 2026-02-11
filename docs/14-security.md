# Security Hardening Runbook
Date: 2026-02-11
Status: Active

This runbook defines the production auth/security baseline for staff APIs.

## 1) Auth Decision Contract
All protected endpoints enforce:
- valid JWT (`signature`, `exp`, issuer/audience)
- approved user exists in DB
- user account is active
- role permission for route
- token not revoked (`iat >= users.revoked_at`)

Standard auth error codes:
- `401 invalid_token`
- `403 access_pending`
- `403 access_denied`
- `403 account_inactive`

## 2) Access Token Lifetime
Target access-token TTL: `5-10 minutes`.

Backend optional enforcement:
- `AUTH_ENFORCE_ACCESS_TTL=true`
- `AUTH_MAX_ACCESS_TOKEN_TTL_SECONDS=600`

If enabled, backend rejects tokens when `exp - iat` exceeds configured max.

## 3) Refresh Token Policy (Neon)
Use Neon Auth settings to enforce:
- refresh token rotation enabled
- reuse detection enabled
- refresh token revocation support enabled

Operational rule:
- if refresh reuse is detected, revoke the entire session family in Neon.

## 4) Immediate Revocation Controls
Revocation primitive:
- `users.revoked_at`

Automatic revoke triggers:
- role changes (`PATCH /api/v1/admin/users/{id}/role`)
- status changes (`PATCH /api/v1/admin/users/{id}/status`)

Manual revoke trigger:
- `POST /api/v1/admin/users/{id}/revoke-sessions`

## 5) Auth Audit Trail
Auth events are persisted in `auth_event` table.

Key event types:
- `denied_access`
- `revoke`
- `manual_revoke`
- `role_change`
- `account_status_change`

Admin query endpoint:
- `GET /api/v1/admin/auth-events`

Supported filters:
- `event_type`
- `user_id`
- `actor_user_id`
- `reason`
- pagination via `limit`, `offset`

## 6) Operational Checks
Daily:
1. Query recent denied events and review spikes (`denied_access`).
2. Confirm role/status changes have matching revoke events.
3. Confirm no admin lockout risk (at least one active admin).

Incident response:
1. Revoke target user's sessions via `POST /api/v1/admin/users/{id}/revoke-sessions`.
2. If broader compromise suspected, rotate Neon signing keys/credentials per Neon guidance.
3. Review `auth_event` timeline and preserve logs for audit.
