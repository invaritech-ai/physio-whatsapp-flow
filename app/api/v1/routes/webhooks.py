"""Webhook endpoints for external service integrations."""

import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlmodel import Session, select

from app.core.config import settings
from app.core.encryption import decrypt_string
from app.db.session import get_session
from app.models import Client, Session as TherapySession, Therapist, TherapistEventType
from app.services.calendly import get_scheduled_event_with_pat

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

logger = logging.getLogger(__name__)


def verify_calendly_signature(payload: bytes, signature: str | None) -> bool:
    """Verify Calendly webhook signature.

    Args:
        payload: Raw request body bytes
        signature: Calendly-Webhook-Signature header value

    Returns:
        True if signature is valid, False otherwise
    """
    if not settings.calendly_webhook_secret:
        logger.warning("CALENDLY_WEBHOOK_SECRET not set - skipping signature verification")
        return True  # Allow in development without secret

    if not signature:
        logger.warning("No Calendly-Webhook-Signature header provided")
        return False

    # Calendly sends signature as: timestamp,signature_value
    # We compute: HMAC-SHA256(timestamp.payload, secret)
    try:
        timestamp, sig_value = signature.split(",", 1)
        signed_payload = f"{timestamp}.{payload.decode()}"
        expected_sig = hmac.new(
            settings.calendly_webhook_secret.encode(),
            signed_payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(sig_value, expected_sig)
    except Exception as e:
        logger.error(f"Signature verification failed: {e}")
        return False


@router.post("/calendly")
async def calendly_webhook(
    request: Request,
    db: Session = Depends(get_session),
    signature: str | None = Header(default=None, alias="Calendly-Webhook-Signature"),
):
    """Handle Calendly webhook events.

    Supported events:
    - invitee.created: When a patient books an appointment

    Webhook payload contains:
    - event: The event type (e.g., "invitee.created")
    - payload: Event data with invitee and event details
    """
    # Get raw body for signature verification
    body = await request.body()

    # Verify signature (if secret is set)
    if not verify_calendly_signature(body, signature):
        logger.warning("Invalid Calendly webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse JSON payload
    try:
        data = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = data.get("event")
    payload = data.get("payload", {})

    logger.info(f"Received Calendly webhook: {event_type}")

    if event_type == "invitee.created":
        return await handle_invitee_created(db, payload)
    elif event_type == "invitee.canceled":
        return await handle_invitee_canceled(db, payload)
    else:
        logger.warning(f"Unhandled Calendly event type: {event_type}")
        return {"status": "ignored", "event": event_type}


async def handle_invitee_created(db: Session, payload: dict) -> dict:
    """Handle invitee.created event - create Session record when patient books.

    Payload structure:
    {
        "event": "https://api.calendly.com/scheduled_events/XXXXX",
        "invitee": {
            "uri": "https://api.calendly.com/scheduled_events/XXXXX/invitees/YYYYY",
            "email": "patient@example.com",
            "name": "John Doe",
            ...
        },
        "event_memberships": [
            {"user": "https://api.calendly.com/users/XXXXX"}
        ],
        "questions_and_answers": [
            {"question": "Phone Number", "answer": "+85212345678"}
        ]
    }
    """
    try:
        # Extract data from payload
        event_uri = payload.get("event")
        invitee = payload.get("invitee", {})
        invitee_uri = invitee.get("uri")
        invitee_name = invitee.get("name")
        questions_and_answers = payload.get("questions_and_answers", [])

        # Extract therapist's Calendly user URI from event memberships
        event_memberships = payload.get("event_memberships", [])
        if not event_memberships:
            logger.error("No event_memberships in webhook payload")
            return {"status": "error", "message": "Missing event memberships"}

        therapist_calendly_uri = event_memberships[0].get("user")

        # Look up therapist by Calendly user URI
        therapist = db.exec(
            select(Therapist).where(Therapist.calendly_user_uri == therapist_calendly_uri)
        ).first()

        if not therapist:
            logger.error(f"No therapist found for Calendly user: {therapist_calendly_uri}")
            return {"status": "error", "message": "Therapist not found"}

        # Fetch scheduled event details via therapist's PAT
        if not therapist.calendly_pat_encrypted:
            logger.error(f"Therapist {therapist.id} has no Calendly PAT")
            return {"status": "error", "message": "Therapist PAT not configured"}

        pat = decrypt_string(therapist.calendly_pat_encrypted)
        event_details = get_scheduled_event_with_pat(event_uri, pat)

        if not event_details:
            logger.error(f"Failed to fetch scheduled event details: {event_uri}")
            return {"status": "error", "message": "Could not fetch event details"}

        # Parse start/end times
        start_time = datetime.fromisoformat(
            event_details["start_time"].replace("Z", "+00:00")
        )
        end_time = datetime.fromisoformat(
            event_details["end_time"].replace("Z", "+00:00")
        )

        # Look up TherapistEventType by the event_type URI from the scheduled event
        event_type_uri = event_details["event_type"]
        therapist_event_type = db.exec(
            select(TherapistEventType).where(
                TherapistEventType.calendly_event_type_uri == event_type_uri
            )
        ).first()

        if not therapist_event_type:
            logger.error(f"No TherapistEventType found for event type URI: {event_type_uri}")
            return {"status": "error", "message": "Event type not found"}

        # Extract phone number from custom questions
        phone_number = None
        for qa in questions_and_answers:
            question = qa.get("question", "").lower()
            if "phone" in question:
                phone_number = qa.get("answer")
                break

        if not phone_number:
            logger.error("No phone number found in booking form")
            return {"status": "error", "message": "Phone number required"}

        # Normalize phone number (remove whatsapp: prefix if present, ensure E.164 format)
        phone_e164 = phone_number.replace("whatsapp:", "").strip()
        if not phone_e164.startswith("+"):
            phone_e164 = f"+{phone_e164}"

        # Find or create client by phone number
        client = db.exec(
            select(Client).where(Client.phone_e164 == phone_e164)
        ).first()

        if not client:
            client = Client(
                phone_e164=phone_e164,
                name=invitee_name or "Unknown",
                conversation_state="IDLE",
            )
            db.add(client)
            db.flush()
            logger.info(f"Created new client: {client.id} ({phone_e164})")
        else:
            if not client.name and invitee_name:
                client.name = invitee_name
                db.add(client)
            logger.info(f"Found existing client: {client.id} ({phone_e164})")

        # Create therapy session record
        session = TherapySession(
            client_id=client.id,
            therapist_id=therapist.id,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=therapist_event_type.duration_minutes,
            calendly_event_uri=event_uri,
            calendly_invitee_uri=invitee_uri,
            source="calendly",
            status="scheduled",
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        logger.info(
            f"Created session {session.id} for client {client.id} "
            f"with therapist {therapist.id} (duration: {session.duration_minutes}min)"
        )

        return {
            "status": "success",
            "session_id": session.id,
            "client_id": client.id,
            "therapist_id": therapist.id,
        }

    except Exception as e:
        logger.exception(f"Error handling invitee.created event: {e}")
        db.rollback()
        return {"status": "error", "message": str(e)}


async def handle_invitee_canceled(db: Session, payload: dict) -> dict:
    """Handle invitee.canceled event - mark session as canceled.

    Payload contains event URI and invitee details.
    """
    try:
        event_uri = payload.get("event")

        # Find session by calendly_event_uri
        stmt = select(TherapySession).where(TherapySession.calendly_event_uri == event_uri)
        session = db.exec(stmt).first()

        if not session:
            logger.warning(f"No session found for canceled event: {event_uri}")
            return {"status": "not_found", "message": "Session not found"}

        # Update session status
        session.status = "cancelled"
        db.add(session)
        db.commit()

        logger.info(f"Marked session {session.id} as cancelled")

        return {
            "status": "success",
            "session_id": session.id,
            "action": "canceled",
        }

    except Exception as e:
        logger.exception(f"Error handling invitee.canceled event: {e}")
        db.rollback()
        return {"status": "error", "message": str(e)}
