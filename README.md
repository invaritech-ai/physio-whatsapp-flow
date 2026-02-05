# Harry - Physio Process Bot

## Overview
This application is a WhatsApp Bot designed to streamline the physiotherapy appointment process. It handles customer inquiries, booking via Calendly, payment verification via FPS, and physiotherapist session management.

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

3.  **Run the Application**:
    ```bash
    uvicorn app.main:app --reload
    ```

4.  **Expose Local Server (for Twilio Webhook)**:
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
*   `app/core/config.py`: Pydantic settings (loads from `.env`).
*   `app/db/session.py`: DB engine/session helpers.
*   `app/services/`: Integrations (Twilio + Calendly).
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

## Git Workflow (Trunk-Based)
*   `main`: production-ready
*   `dev`: integration branch
*   `feat/<name>`: short-lived feature branches, merged into `dev`
*   Promote `dev` → `main` via PR when stable and tested
