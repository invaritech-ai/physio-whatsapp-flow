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
        secrets = [
            secret.strip()
            for secret in settings.calendly_webhook_secret.split(",")
            if secret.strip()
        ]
        if not secrets:
            logger.warning("CALENDLY_WEBHOOK_SECRET configured but empty after parsing")
            return True

        for secret in secrets:
            expected_sig = hmac.new(
                secret.encode(),
                signed_payload.encode(),
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(sig_value, expected_sig):
                return True

        return False
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
    - invitee.canceled: When a patient cancels an appointment
    - invitee.rescheduled: Optional legacy/custom event handling (not required for subscription)

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
    elif event_type == "invitee.rescheduled":
        # Kept as a compatibility fallback. Current subscription setup relies on
        # invitee.created + invitee.canceled for reschedule flows.
        return await handle_invitee_rescheduled(db, payload)
    elif event_type == "invitee.canceled":
        return await handle_invitee_canceled(db, payload)
    else:
        logger.warning(f"Unhandled Calendly event type: {event_type}")
        return {"status": "ignored", "event": event_type}


def _extract_uri(value: object) -> str | None:
    """Extract URI from a Calendly webhook field that may be str or nested dict."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("uri", "event", "scheduled_event", "scheduled_event_uri"):
            nested = value.get(key)
            if isinstance(nested, str):
                return nested
            if isinstance(nested, dict):
                uri = nested.get("uri")
                if isinstance(uri, str):
                    return uri
    return None


def _payload_uri(payload: dict, *keys: str) -> str | None:
    for key in keys:
        uri = _extract_uri(payload.get(key))
        if uri:
            return uri
    return None


def _find_session_by_refs(
    db: Session,
    *,
    event_uri: str | None = None,
    invitee_uri: str | None = None,
) -> TherapySession | None:
    if event_uri:
        session = db.exec(
            select(TherapySession).where(TherapySession.calendly_event_uri == event_uri)
        ).first()
        if session:
            return session

    if invitee_uri:
        session = db.exec(
            select(TherapySession).where(TherapySession.calendly_invitee_uri == invitee_uri)
        ).first()
        if session:
            return session

    return None


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
        event_uri = _payload_uri(payload, "event", "new_event", "new_event_uri")
        invitee = payload.get("invitee", {})
        invitee_uri = _extract_uri(invitee) or _payload_uri(payload, "new_invitee", "new_invitee_uri")
        old_event_uri = _payload_uri(payload, "old_event", "old_event_uri")
        old_invitee_uri = _payload_uri(payload, "old_invitee", "old_invitee_uri")
        is_rescheduled = bool(payload.get("rescheduled")) or bool(old_event_uri or old_invitee_uri)
        invitee_name = invitee.get("name")
        questions_and_answers = payload.get("questions_and_answers", [])

        if not event_uri:
            logger.error("No event URI found in invitee.created payload")
            return {"status": "error", "message": "Missing event URI"}

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
                TherapistEventType.therapist_id == therapist.id,
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

        # Upsert session:
        # - idempotent on current event/invitee URIs
        # - for reschedules, migrate old session forward when old refs are present
        session = _find_session_by_refs(db, event_uri=event_uri, invitee_uri=invitee_uri)
        if not session and is_rescheduled:
            session = _find_session_by_refs(
                db,
                event_uri=old_event_uri,
                invitee_uri=old_invitee_uri,
            )

        if session:
            session.client_id = client.id
            session.therapist_id = therapist.id
            session.start_time = start_time
            session.end_time = end_time
            session.duration_minutes = therapist_event_type.duration_minutes
            session.calendly_event_uri = event_uri
            if invitee_uri:
                session.calendly_invitee_uri = invitee_uri
            session.source = "calendly"
            session.status = "scheduled"
            session.updated_at = datetime.now(timezone.utc)
            db.add(session)
            db.commit()
            db.refresh(session)

            logger.info(
                "Updated existing session %s via invitee.created (rescheduled=%s)",
                session.id,
                is_rescheduled,
            )
        else:
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
        event_uri = _payload_uri(payload, "event", "old_event", "old_event_uri")
        invitee_uri = _payload_uri(payload, "invitee", "old_invitee", "old_invitee_uri")

        session = _find_session_by_refs(db, event_uri=event_uri, invitee_uri=invitee_uri)

        if not session:
            logger.warning(f"No session found for canceled event: {event_uri or invitee_uri}")
            return {"status": "not_found", "message": "Session not found"}

        # Update session status
        session.status = "cancelled"
        session.updated_at = datetime.now(timezone.utc)
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


async def handle_invitee_rescheduled(db: Session, payload: dict) -> dict:
    """Handle invitee.rescheduled event - move/update existing session to new time."""
    try:
        old_event_uri = _payload_uri(payload, "old_event", "old_event_uri")
        new_event_uri = _payload_uri(payload, "new_event", "new_event_uri", "event")
        old_invitee_uri = _payload_uri(payload, "old_invitee", "old_invitee_uri")
        new_invitee_uri = _payload_uri(payload, "new_invitee", "new_invitee_uri", "invitee")

        lookup_order = [
            ("calendly_event_uri", old_event_uri),
            ("calendly_invitee_uri", old_invitee_uri),
            ("calendly_event_uri", new_event_uri),
            ("calendly_invitee_uri", new_invitee_uri),
        ]

        session = None
        for field_name, uri in lookup_order:
            if not uri:
                continue
            if field_name == "calendly_event_uri":
                session = db.exec(
                    select(TherapySession).where(TherapySession.calendly_event_uri == uri)
                ).first()
            else:
                session = db.exec(
                    select(TherapySession).where(TherapySession.calendly_invitee_uri == uri)
                ).first()
            if session:
                break

        if not session:
            logger.warning(
                "No session found for rescheduled event (old_event=%s, old_invitee=%s, new_event=%s, new_invitee=%s)",
                old_event_uri,
                old_invitee_uri,
                new_event_uri,
                new_invitee_uri,
            )
            return {"status": "not_found", "message": "Session not found"}

        therapist = db.get(Therapist, session.therapist_id)
        if not therapist:
            logger.error(f"No therapist found for session {session.id}")
            return {"status": "error", "message": "Therapist not found"}

        if not therapist.calendly_pat_encrypted:
            logger.error(f"Therapist {therapist.id} has no Calendly PAT")
            return {"status": "error", "message": "Therapist PAT not configured"}

        target_event_uri = new_event_uri or session.calendly_event_uri
        if not target_event_uri:
            logger.error(f"No target event URI in rescheduled payload for session {session.id}")
            return {"status": "error", "message": "Missing event URI"}

        pat = decrypt_string(therapist.calendly_pat_encrypted)
        event_details = get_scheduled_event_with_pat(target_event_uri, pat)
        if not event_details:
            logger.error(f"Failed to fetch scheduled event details for reschedule: {target_event_uri}")
            return {"status": "error", "message": "Could not fetch event details"}

        start_time = datetime.fromisoformat(
            event_details["start_time"].replace("Z", "+00:00")
        )
        end_time = datetime.fromisoformat(
            event_details["end_time"].replace("Z", "+00:00")
        )
        event_type_uri = event_details["event_type"]

        therapist_event_type = db.exec(
            select(TherapistEventType).where(
                TherapistEventType.therapist_id == therapist.id,
                TherapistEventType.calendly_event_type_uri == event_type_uri,
            )
        ).first()

        duration_minutes = session.duration_minutes
        if therapist_event_type:
            duration_minutes = therapist_event_type.duration_minutes

        existing_new_session = None
        if target_event_uri and target_event_uri != session.calendly_event_uri:
            existing_new_session = db.exec(
                select(TherapySession).where(
                    TherapySession.calendly_event_uri == target_event_uri,
                    TherapySession.id != session.id,
                )
            ).first()

        if existing_new_session:
            # If a new-event session already exists (out-of-order webhooks), keep it
            # as canonical and mark the old session cancelled.
            existing_new_session.start_time = start_time
            existing_new_session.end_time = end_time
            existing_new_session.duration_minutes = duration_minutes
            existing_new_session.status = "scheduled"
            if new_invitee_uri:
                existing_new_session.calendly_invitee_uri = new_invitee_uri
            existing_new_session.updated_at = datetime.now(timezone.utc)

            session.status = "cancelled"
            session.updated_at = datetime.now(timezone.utc)

            db.add(existing_new_session)
            db.add(session)
            db.commit()

            logger.info(
                "Rescheduled session merged: old_session=%s new_session=%s",
                session.id,
                existing_new_session.id,
            )
            return {
                "status": "success",
                "session_id": existing_new_session.id,
                "action": "rescheduled",
            }

        session.start_time = start_time
        session.end_time = end_time
        session.duration_minutes = duration_minutes
        session.status = "scheduled"
        session.calendly_event_uri = target_event_uri
        if new_invitee_uri:
            session.calendly_invitee_uri = new_invitee_uri
        session.updated_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()

        logger.info("Rescheduled session %s to event %s", session.id, target_event_uri)
        return {
            "status": "success",
            "session_id": session.id,
            "action": "rescheduled",
        }

    except Exception as e:
        logger.exception(f"Error handling invitee.rescheduled event: {e}")
        db.rollback()
        return {"status": "error", "message": str(e)}
