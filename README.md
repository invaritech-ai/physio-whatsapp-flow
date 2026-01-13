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
*   **Actions**:
    *   **Start**: Physio replies `start <appointment_id>` → Bot updates status to `started` and informs the Physio of the payment status (e.g., "Approved").
    *   **Cancel**: Physio replies `cancel` (or `cancel <id>`) → Bot acknowledges the cancellation.

## Prerequisites & Setup

### Requirements
*   **Python 3.9+**
*   **Twilio Account** (for WhatsApp Sandbox or Production API)
*   **Calendly Account** (with API Token)
*   **ngrok** (for local development webhook exposure)

### Environment Variables
Create a `.env` file in the root directory with the following keys:

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
    uvicorn main:app --reload
    ```

4.  **Expose Local Server (for Twilio Webhook)**:
    ```bash
    ngrok http 8000
    ```
    *   Copy the generated HTTPS URL (e.g., `https://xxxx.ngrok.io`).
    *   Update your Twilio WhatsApp Sandbox "When a message comes in" URL to: `https://xxxx.ngrok.io/whatsapp`

## Project Structure
*   `main.py`: Entry point, FastAPI app, webhook handler, and scheduler.
*   `bot_logic.py`: Core logic for handling messages and routing based on user roles.
*   `models.py`: Database models (User, Appointment, Payment).
*   `services/`:
    *   `twilio_client.py`: Wrapper for Twilio API.
    *   `calendly.py`: Wrapper for Calendly API (Availability & Booking).
