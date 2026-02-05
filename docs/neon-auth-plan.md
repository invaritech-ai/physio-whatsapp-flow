# Neon Auth Integration Plan (React + FastAPI)
Date: 2026-02-05
Status: Draft plan (no code changes yet)

## Goals
- Use Neon Auth for user authentication.
- React frontend handles magic link/OTP as primary login flow.
- FastAPI backend verifies Neon Auth JWTs for protected endpoints.
- Avoid exposing backend endpoints to unauthenticated requests, regardless of client (browser, Postman, etc.).

## Assumptions
- Neon Auth is enabled.
- You already have both the Auth Base URL and JWKS URL.
- Frontend is in a separate repo and deployed separately.
- Database connection uses Neon Postgres (already set in `.env`).

## Architecture (Chosen)
- Frontend uses Neon Auth SDK to sign in users via magic link/OTP.
- Frontend receives an auth session/token and sends it to the backend in the `Authorization: Bearer <token>` header.
- Backend verifies tokens using the JWKS URL and enforces authorization on protected routes.

## Plan: Backend (FastAPI)
1. **Config & secrets**
   - Add env vars (names can be adjusted):
     - `NEON_AUTH_URL` (Auth Base URL)
     - `NEON_JWKS_URL` (JWKS URL)
     - `NEON_JWT_ISSUER` (expected issuer)
     - `NEON_JWT_AUDIENCE` (expected audience)
   - Confirm issuer/audience values from Neon Auth configuration.

2. **JWT verification module**
   - Add a small auth utility that:
     - Parses the `Authorization` header.
     - Fetches JWKS and caches it (in-memory, with TTL).
     - Verifies token signature and validates `iss`, `aud`, `exp`.
     - Extracts Neon Auth user ID and email/phone claims.
   - Decide Python JWT library (examples: `python-jose` or `PyJWT`).

3. **Dependency injection**
   - Create a `get_current_user()` dependency for protected endpoints.
   - Return 401 for missing/invalid tokens.
   - Return 403 for valid token but insufficient privileges.

4. **User mapping strategy**
   - Decide how Neon Auth users map to `User` table:
     - Option A: add `neon_user_id` to `User`.
     - Option B: create `AuthUser` table with a 1:1 link to `User`.
   - For first login, provision or link the user in DB.

5. **Role enforcement**
   - Map Neon Auth users to roles (`customer`, `admin`, `physio`).
   - Enforce role checks in endpoints with a simple guard.

6. **Integrate with existing flows**
   - Decide which endpoints are protected:
     - Anything not used by Twilio/Calendly webhooks should require auth.
   - Leave webhook routes with their own signature verification.

## Plan: Frontend (React)
1. **Auth client setup**
   - Install `@neondatabase/neon-js` and configure `VITE_NEON_AUTH_URL`.
   - Instantiate auth client once at app startup.

2. **Magic link / OTP flow**
   - Implement sign-in screen that requests magic link/OTP.
   - After success, store session/token in memory or secure storage.

3. **Backend calls**
   - Attach `Authorization: Bearer <token>` to all API requests.
   - Refresh token/session as needed.

4. **Logout**
   - Clear session and client state.

## Database & Migrations
- If you add `neon_user_id` or an auth table, update `app/models.py` and create an Alembic migration.
- Backfill existing users if needed.

## Security Checklist
- Token verification is mandatory for all protected endpoints.
- Validate `iss`, `aud`, and `exp` on every request.
- Cache JWKS keys and handle key rotation gracefully.
- Never accept tokens in query params.
- Keep webhook endpoints protected by their own signature verification.

## Test Plan
- Frontend login:
  - Request magic link/OTP and confirm sign-in works.
- Backend token verification:
  - Valid token succeeds.
  - Expired token returns 401.
  - Wrong issuer/audience returns 401.
  - Missing token returns 401.
- Authorization:
  - Customer cannot access admin/physio endpoints.
- Regression:
  - Twilio webhook still works with signature verification.

## Rollout Steps
1. Implement backend verification and deploy.
2. Implement frontend magic link flow and deploy.
3. Validate end-to-end in staging.
4. Move to production.

## Open Questions
- Confirm Neon Auth issuer and audience values.
- Decide whether to store `neon_user_id` on `User` or in a new table.
- Decide how to map existing phone-based users to Neon Auth users.
