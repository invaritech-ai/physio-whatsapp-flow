# Harry - Physio Process Bot

## Overview
This application is a WhatsApp Bot designed to streamline the physiotherapy appointment process. It handles customer inquiries, booking via Calendly, payment verification via FPS, and physiotherapist session management.

---

## 🚀 Quick Start

**📖 [Follow the Setup Guide](docs/00-setup-guide.md)** - Complete numbered documentation

### **Essential Setup Steps:**

1. **Generate Encryption Key** (REQUIRED)
   ```bash
   python scripts/generate_encryption_key.py
   ```

2. **Configure Environment**
   ```bash
   cp .env.example .env
   # Edit .env with your keys (see .env.example for all options)
   ```

3. **Setup Database**
   ```bash
   alembic upgrade head
   ```

4. **Start Services**
   ```bash
   # Terminal 1: Redis
   redis-server

   # Terminal 2: Celery
   uv run celery -A app.worker:celery_app worker --loglevel=info

   # Terminal 3: Celery Beat (periodic sync jobs)
   uv run celery -A app.worker:celery_app beat --loglevel=info

   # Terminal 4: FastAPI
   uv run uvicorn app.main:app --reload
   ```

5. **Verify**
   ```bash
   curl http://localhost:8000/health
   ```

### **📚 Documentation Index**

- **[00-setup-guide.md](docs/00-setup-guide.md)** ← START HERE
- [03-encryption-setup.md](docs/03-encryption-setup.md) - Encryption key setup (CRITICAL)
- [09-therapist-onboarding.md](docs/09-therapist-onboarding.md) - Onboard therapists
- [12-therapist-self-service-api.md](docs/12-therapist-self-service-api.md) - API reference
- [v1-matching-spec.md](docs/v1-matching-spec.md) - Matching algorithm
- [encrypted-pat-storage.md](docs/encrypted-pat-storage.md) - Security details

### **⚙️ Key Environment Variables**

All variables are configurable via `.env` (see [.env.example](.env.example)):

**Required:**
- `DATABASE_URL` - PostgreSQL connection string
- `ENCRYPTION_KEY` - For encrypting therapist Calendly PATs
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` - WhatsApp bot
- `CALENDLY_API_TOKEN` - Organization token (optional fallback)
- `NEON_JWKS_URL`, `NEON_JWT_ISSUER` - Web UI authentication

**Optional:**
- `PUBLIC_BASE_URL` - For webhooks
- `DEFAULT_CURRENCY` - Defaults to HKD
- `DEBUG_MODE` - Enable debug logging
- `CELERY_BROKER_URL` - Redis URL for background tasks

---

## Bot Logic & Flows

### 1. Customer Flow
*   **Engagement**:
    *   **User Greeting**: "Hi" or "Hello" → Bot greets and asks for the desired session duration (30, 45, or 60 minutes).
    *   **Availability Check**: User mentions "30 min", "45 min", etc. → Bot checks Calendly for available slots in the next 3 days (9 AM - 5 PM) and proposes the first available time.
*   **Booking**:
    *   **Request Link**: User replies "book" → Bot provides a specific Calendly booking link.
    *   **Confirmation**: User replies "booked" (after completing the external Calendly process) → Bot records the appointment internally (`status: scheduled`) and requests payment.
*   **Payment**:
    *   **Submission**: User uploads an image (receipt) or mentions keywords like "paid", "receipt", "FPS".
    *   **Processing**: Bot records a pending payment and notifies the Admin for approval.

### 2. Admin Flow
*   **Triggers**:
    *   Admin receives a WhatsApp notification whenever a customer uploads valid payment proof or claims payment.
*   **Actions**:
    *   **Approve Payment**: Admin replies `approve <payment_id>` (e.g., "approve 12").
    *   **Result**: Bot marks the payment as `approved` and sends a confirmation message to the **Customer**, securing their slot.

### 3. Physiotherapist Flow
*   **Notifications**:
    *   **Upcoming Session**: A background scheduler runs every 5 minutes. 30 minutes before a session, the **Customer** gets a reminder.
    *   **Start Session**: At the appointment time, the **Physiotherapist** receives a message: *"Appointment Starting ID: X... Reply 'start X' or 'cancel X'"*.
    *   **At Session End Time** (based on selected duration):
        *   Bot automatically triggers payment collection flow
        *   Physio receives: *"Session completed. How was payment handled?"*
*   **Actions**:
    *   **Start Session**: Physio replies `start <appointment_id>` → Bot updates status to `started` and informs the Physio of the payment status (e.g., "Approved").
    *   **Add Notes**: During an active session, Physio can type `add notes` to enter note-taking mode:
        *   Each message becomes a timestamped note about the client
        *   Type `done` to exit note-taking mode
        *   Can re-enter note mode multiple times during a session
        *   Original text case is preserved for clinical accuracy
    *   **View Notes**: Physio can type `view notes <appointment_id>` to view all notes for a specific session (e.g., "view notes 1")
    *   **Cancel**: Physio replies `cancel` (or `cancel <id>`) → Bot acknowledges the cancellation.

### 4.   Payment Collection Flow (Triggered automatically when session ends):
*  **Payment Status Question**: Bot asks: *"How was payment handled? Reply with:1️⃣ Payment received2️⃣ FPS 3️⃣ Consolidating with other session"*
*  **Payment Status Options**:
    *   **Option 1 - Payment received**: Bot asks for payment method:
            *   *"What payment method was used? Reply with 'cash' or 'card'"*
            *   Physio selects Cash or Card → Bot records and marks session as completed
    *   **Option 2 - FPS**: Bot records FPS payment and marks session as completed
    *   **Option 3 - Consolidating**: Bot records consolidation with other session and marks session as completed
*  **All responses are logged** to console with timestamps for record-keeping

## Prerequisites & Setup

### Requirements
*   **Python 3.9+**
*   **Redis** (for Celery task queue)
*   **Twilio Account** (for WhatsApp Sandbox or Production API)
*   **Calendly Account** (with API Token)
*   **ngrok** (for local development webhook exposure)

### Environment Variables
Create a `.env` file in the root directory with the following keys (or copy `.env.example`):

```env
# Twilio Configuration
TWILIO_ACCOUNT_SID=your_sid_here
TWILIO_AUTH_TOKEN=your_token_here
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886

# Calendly Configuration
CALENDLY_API_TOKEN=your_calendly_token

# Application Roles (Phone numbers in whatsapp:+1234567890 format)
ADMIN_PHONE_NUMBER=whatsapp:+1234567890
PHYSIO_PHONE_NUMBER=whatsapp:+0987654321

# Database (Optional, defaults to local SQLite)
DATABASE_URL=sqlite:///./physio.db

# Celery + Redis (async task queue)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Debug Mode (Optional, defaults to false)
# When true: Messages are logged but not sent via Twilio, allows manual role switching
DEBUG_MODE=false
```

### Installation

1.  **Clone the repository**:
    ```bash
    git clone <repository-url>
    cd <repository-folder>
    ```

2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Start Redis** (required for Celery):
    ```bash
    docker run -d --name redis -p 6379:6379 redis:7-alpine
    ```

4.  **Start Celery Worker**:
    ```bash
    uv run celery -A app.worker:celery_app worker --loglevel=info
    ```

5.  **Start Celery Beat**:
    ```bash
    uv run celery -A app.worker:celery_app beat --loglevel=info
    ```

6.  **Run the Application**:
    ```bash
    uv run uvicorn app.main:app --reload
    ```

7.  **Expose Local Server (for Twilio Webhook)**:
    ```bash
    ngrok http 8000
    ```
    *   Copy the generated HTTPS URL (e.g., `https://xxxx.ngrok.io`).
    *   Update your Twilio WhatsApp Sandbox "When a message comes in" URL to: `https://xxxx.ngrok.io/api/v1/whatsapp`

## Project Structure
*   `app/main.py`: FastAPI app, webhook handler, and (temporary) scheduler.
*   `app/bot_logic.py`: Core logic for handling messages and routing based on user roles.
*   `app/models/`: SQLModel database models (User, Appointment, Payment, SessionNote).
*   `app/api/`: Route registry, versioned API modules (`/api/v1/*`).
    *   `app/api/v1/routes/session_notes.py`: REST API for session notes (CRUD operations).
*   `app/core/config.py`: Pydantic settings (loads from `.env`).
*   `app/db/session.py`: DB engine/session helpers.
*   `app/services/`: Integrations (Twilio + Calendly).
*   `app/worker.py`: Celery app configuration.
*   `app/tasks/`: Background tasks (WhatsApp message processing, etc.).
*   `alembic/`: Database migrations.
*   `docs/`: Project documentation.

Detailed structure: [docs/project-structure.md](docs/project-structure.md)

## Database Migrations (Alembic)
Detailed guide: [docs/alembic.md](docs/alembic.md)

Run these from the repo root:

```bash
alembic upgrade head
```

Create a new migration after model changes:

```bash
alembic revision --autogenerate -m "describe change"
```

## API Endpoints

### WhatsApp Webhook
*   `POST /api/v1/whatsapp` - Twilio webhook for incoming WhatsApp messages (enqueues Celery task)
*   `POST /api/v1/whatsapp/test` - Manual test endpoint for sending messages (JSON format)

### Session Notes API
*   `GET /api/v1/session-notes?appointment_id={id}` - List notes for an appointment
*   `GET /api/v1/session-notes?physio_id={id}` - List notes by physio
*   `GET /api/v1/session-notes?appointment_id={id}&physio_id={id}` - List notes (filtered)
*   `GET /api/v1/session-notes/{note_id}` - Get a single note
*   `POST /api/v1/session-notes` - Create a new note
*   `PATCH /api/v1/session-notes/{note_id}` - Update a note
*   `DELETE /api/v1/session-notes/{note_id}` - Delete a note

Documentation: [SESSION_NOTES_API.md](SESSION_NOTES_API.md)

### Web API (Protected)
*   `GET /api/v1/me` - Get current authenticated user (Neon Auth JWT)

### Interactive Documentation
*   Swagger UI: `http://localhost:8000/docs`
*   ReDoc: `http://localhost:8000/redoc`

## Git Workflow (Trunk-Based)
*   `main`: production-ready
*   `dev`: integration branch
*   `feat/<name>`: short-lived feature branches, merged into `dev`
*   Promote `dev` → `main` via PR when stable and tested
