# Project Structure
Date: 2026-02-05

This document explains how the backend is organized and where to add new code as the project grows.

---

## Top-Level Layout
- `app/`: Application code (FastAPI, models, services, bot logic).
- `alembic/`: Database migrations and Alembic configuration.
- `docs/`: Project documentation.
- `.env.example`: Environment variable template.
- `requirements.txt`: Python dependencies.

---

## Application (`app/`)

**Entry Point**
- `app/main.py`: FastAPI app creation, scheduler, and middleware setup. The API routes are registered here.

**API Routing**
- `app/api/`: API registry and root route.
- `app/api/root.py`: Health endpoint at `GET /`.
- `app/api/v1/`: Versioned API (`/api/v1/*`).
- `app/api/v1/routes/`: Route modules by concern (auth, whatsapp, etc.).

**Models**
- `app/models/`: SQLModel models split by domain.
- `app/models/__init__.py`: Exports all models so Alembic loads metadata.

**Core & Config**
- `app/core/`: Cross-cutting utilities (auth, config).
- `app/core/config.py`: Settings loaded from `.env`.
- `app/core/auth.py`: JWT verification for Neon Auth and `/me` dependency.

**Database**
- `app/db/session.py`: SQLModel engine and session helpers.

**Services**
- `app/services/`: External integrations (Twilio, Calendly).

**Bot Logic**
- `app/bot_logic.py`: WhatsApp flow logic and state transitions.

---

## Migrations (`alembic/`)
- `alembic/env.py`: Alembic runtime configuration and SQLModel metadata loading.
- `alembic/versions/`: Migration history.

---

## Extending the Project
- Add new routes under `app/api/v1/routes/` and include them in `app/api/v1/__init__.py`.
- Add new models under `app/models/` and export them in `app/models/__init__.py`.
- Use Alembic to generate and apply schema changes.
