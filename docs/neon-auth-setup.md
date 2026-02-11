# Neon Auth Setup (React + FastAPI)
Date: 2026-02-05
Status: Active

This document explains how to configure Neon Auth for the React frontend and FastAPI backend, and how to deploy to production.

---

## 1) Prerequisites
- Neon project with **Auth enabled**.
- Auth Base URL and JWKS URL from Neon Console.
- Frontend deployed separately from backend.

---

## 2) Neon Console Configuration
1. **Auth URL + JWKS URL**
   - Copy these into your frontend and backend environment variables.
2. **Allowed Domains**
   - Add your frontend domains (prod + staging + localhost) to the allowed redirect list.
3. **SMTP (recommended)**
   - Configure custom SMTP for magic-link/OTP deliverability.

---

## 3) Frontend Setup (React)
**Required env vars** (in the frontend repo):
```
VITE_NEON_AUTH_URL=<Auth Base URL>
VITE_API_BASE_URL=<FastAPI base URL>
```

**Flow**
- Use Neon Auth SDK in React.
- User signs in via magic link/OTP.
- Frontend attaches `Authorization: Bearer <token>` to API calls.

---

## 4) Backend Setup (FastAPI)
**Required env vars** (in this repo):
```
NEON_AUTH_URL=<Auth Base URL>
NEON_JWKS_URL=<JWKS URL>
NEON_JWT_ISSUER=<Issuer from token>
NEON_JWT_AUDIENCE=<Audience from token>
```

**Optional hardening env vars**:
```
AUTH_ENFORCE_ACCESS_TTL=true
AUTH_MAX_ACCESS_TOKEN_TTL_SECONDS=600
```

**Endpoints**
- `GET /me` validates the Bearer token and returns basic user info.

---

## 5) Production Deployment
### Backend
1. **Set env vars**
   - Ensure all Neon Auth vars and production `APP_BASE_URL` / `WEB_BASE_URL` are set.
2. **CORS**
   - Lock CORS to your production frontend domain.
3. **HTTPS**
   - Serve the API over HTTPS (required for secure cookies and browser auth flows).
4. **Secrets**
   - Store secrets in your platform’s secret manager (not in repo).

### Frontend
1. **Set env vars**
   - `VITE_NEON_AUTH_URL` and `VITE_API_BASE_URL` for production.
2. **Build + deploy**
   - Build with `npm run build` and deploy the static output.
3. **Domain allowlist**
   - Confirm your production domain is listed in Neon Auth allowed domains.

---

## 6) Production Verification Checklist
- Login succeeds and email delivery works.
- `/me` returns a 200 with valid token.
- `/me` returns 401 for invalid or expired token.
- CORS only allows production frontend.
- Admin revoke endpoint works: `POST /api/v1/admin/users/{id}/revoke-sessions`.
- Auth events visible: `GET /api/v1/admin/auth-events`.

---

## 7) Troubleshooting
- **401 Unauthorized**: issuer/audience mismatch in backend env.
- **CORS errors**: missing frontend domain in backend CORS config.
- **OTP not delivered**: SMTP not configured or mail provider blocked.

See also: [14-security.md](14-security.md) for the full hardening runbook.
