"""Webhook endpoints for external service integrations."""

import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlmodel import Session, select

from app.core.encryption import decrypt_string
from app.db.session import get_session
from app.models import Client, Session as TherapySession, Therapist, TherapistEventType
from app.services.calendly import get_scheduled_event_with_pat

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

logger = logging.getLogger(__name__)


def verify_calendly_signature(
    payload: bytes,
    signature: str | None,
    secrets: list[str],
) -> bool:
    """Verify Calendly webhook signature.

    Args:
        payload: Raw request body bytes
        signature: Calendly-Webhook-Signature header value

    Returns:
        True if signature is valid, False otherwise
    """
    logger.debug("[DEBUG-SIG] verify_calendly_signature called")
    logger.debug("[DEBUG-SIG] signature header present: %s", signature is not None)
    logger.debug("[DEBUG-SIG] number of secrets to try: %d", len(secrets))

    if not signature:
        logger.warning("No Calendly-Webhook-Signature header provided")
        return False

    if not secrets:
        logger.warning("No stored Calendly webhook signing keys found for incoming payload")
        return False

    # Calendly sends signature as: t=<timestamp>,v1=<signature_hex>
    # We compute: HMAC-SHA256("<timestamp>.<payload>", secret)
    try:
        t_part, v1_part = signature.split(",", 1)
        timestamp = t_part.removeprefix("t=")
        sig_value = v1_part.removeprefix("v1=")
        logger.debug("[DEBUG-SIG] parsed timestamp=%s, sig_value=%s…", timestamp, sig_value[:16])
        signed_payload = f"{timestamp}.{payload.decode()}"
        logger.debug("[DEBUG-SIG] signed_payload length=%d", len(signed_payload))
        for i, secret in enumerate(secret.strip() for secret in secrets if secret.strip()):
            expected_sig = hmac.new(
                secret.encode(),
                signed_payload.encode(),
                hashlib.sha256,
            ).hexdigest()
            logger.debug(
                "[DEBUG-SIG] secret[%d]: key=%s…, expected=%s…, received=%s…, match=%s",
                i, secret[:8], expected_sig[:16], sig_value[:16],
                hmac.compare_digest(sig_value, expected_sig),
            )
            if hmac.compare_digest(sig_value, expected_sig):
                return True

        logger.debug("[DEBUG-SIG] No secret matched the signature")
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
    # Parse JSON payload before signature verification so we can resolve therapist
    # specific signing keys stored in database.
    logger.debug("[DEBUG-WH] === Incoming Calendly webhook ===")
    logger.debug("[DEBUG-WH] Calendly-Webhook-Signature header: %s", signature)
    try:
        body = await request.body()
        data = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = data.get("event")
    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}

    logger.debug("[DEBUG-WH] event_type=%s", event_type)
    logger.debug("[DEBUG-WH] payload keys=%s", list(payload.keys()) if payload else "empty")
    scheduled_event = payload.get("scheduled_event", {})
    logger.debug("[DEBUG-WH] scheduled_event keys=%s", list(scheduled_event.keys()) if isinstance(scheduled_event, dict) else type(scheduled_event))
    logger.debug("[DEBUG-WH] event_memberships=%s", scheduled_event.get("event_memberships") if isinstance(scheduled_event, dict) else None)
    logger.debug("[DEBUG-WH] raw body length=%d bytes", len(body))

    secrets = _resolve_calendly_signing_secrets(db, payload)
    logger.debug("[DEBUG-WH] resolved %d signing secrets", len(secrets))
    if not verify_calendly_signature(body, signature, secrets):
        logger.warning("Invalid Calendly webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

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


def _therapist_signing_key(therapist: Therapist) -> str | None:
    if not therapist.calendly_webhook_signing_key_encrypted:
        logger.debug(
            "[DEBUG-KEY] therapist_id=%s has NO stored signing key (field is NULL)",
            therapist.id,
        )
        return None
    try:
        decrypted = decrypt_string(therapist.calendly_webhook_signing_key_encrypted)
        logger.debug(
            "[DEBUG-KEY] therapist_id=%s signing key decrypted OK (key=%s…, encrypted_len=%d)",
            therapist.id,
            decrypted[:8] if decrypted else "EMPTY",
            len(therapist.calendly_webhook_signing_key_encrypted),
        )
        return decrypted
    except Exception:
        logger.exception(
            "Failed to decrypt Calendly webhook signing key for therapist_id=%s",
            therapist.id,
        )
        return None


def _resolve_calendly_signing_secrets(db: Session, payload: dict) -> list[str]:
    therapist_ids: set[int] = set()
    secrets: list[str] = []

    logger.debug("[DEBUG-RESOLVE] === Resolving signing secrets ===")

    # Primary lookup: therapist Calendly user URI in event memberships.
    # Calendly nests event_memberships under payload.scheduled_event, not at the top level.
    scheduled_event = payload.get("scheduled_event")
    if isinstance(scheduled_event, dict):
        memberships = scheduled_event.get("event_memberships") or []
    else:
        memberships = payload.get("event_memberships") or []
    logger.debug("[DEBUG-RESOLVE] event_memberships count=%d, raw=%s", len(memberships) if isinstance(memberships, list) else 0, memberships)
    if isinstance(memberships, list):
        for membership in memberships:
            if not isinstance(membership, dict):
                logger.debug("[DEBUG-RESOLVE] skipping non-dict membership: %s", membership)
                continue
            user_uri = _extract_uri(membership.get("user"))
            logger.debug("[DEBUG-RESOLVE] extracted user_uri=%s from membership", user_uri)
            if not user_uri:
                continue
            therapist = db.exec(
                select(Therapist).where(Therapist.calendly_user_uri == user_uri)
            ).first()
            if therapist and therapist.id:
                logger.debug(
                    "[DEBUG-RESOLVE] MATCHED therapist_id=%s by calendly_user_uri=%s",
                    therapist.id, user_uri,
                )
                therapist_ids.add(therapist.id)
                key = _therapist_signing_key(therapist)
                if key:
                    secrets.append(key)
                else:
                    logger.debug("[DEBUG-RESOLVE] therapist_id=%s matched but has no signing key", therapist.id)
            else:
                # Also log what URIs we DO have in the DB for comparison
                all_therapists = db.exec(select(Therapist)).all()
                db_uris = [(t.id, t.calendly_user_uri) for t in all_therapists]
                logger.debug(
                    "[DEBUG-RESOLVE] NO therapist found for calendly_user_uri=%s. "
                    "All therapists in DB: %s",
                    user_uri, db_uris,
                )

    # Fallback lookup: map webhook event/invitee URIs back to existing sessions.
    event_uris: set[str] = set()
    invitee_uris: set[str] = set()
    for key in ("event", "new_event", "new_event_uri", "old_event", "old_event_uri"):
        uri = _extract_uri(payload.get(key))
        if uri:
            event_uris.add(uri)
    for key in ("invitee", "new_invitee", "new_invitee_uri", "old_invitee", "old_invitee_uri"):
        uri = _extract_uri(payload.get(key))
        if uri:
            invitee_uris.add(uri)

    logger.debug("[DEBUG-RESOLVE] fallback event_uris=%s, invitee_uris=%s", event_uris, invitee_uris)

    for event_uri in event_uris:
        session = db.exec(
            select(TherapySession).where(TherapySession.calendly_event_uri == event_uri)
        ).first()
        if session and session.therapist_id and session.therapist_id not in therapist_ids:
            therapist = db.get(Therapist, session.therapist_id)
            if therapist and therapist.id:
                logger.debug("[DEBUG-RESOLVE] MATCHED therapist_id=%s via event_uri fallback", therapist.id)
                therapist_ids.add(therapist.id)
                key = _therapist_signing_key(therapist)
                if key:
                    secrets.append(key)
        else:
            logger.debug("[DEBUG-RESOLVE] no session found for event_uri=%s", event_uri)

    for invitee_uri in invitee_uris:
        session = db.exec(
            select(TherapySession).where(TherapySession.calendly_invitee_uri == invitee_uri)
        ).first()
        if session and session.therapist_id and session.therapist_id not in therapist_ids:
            therapist = db.get(Therapist, session.therapist_id)
            if therapist and therapist.id:
                logger.debug("[DEBUG-RESOLVE] MATCHED therapist_id=%s via invitee_uri fallback", therapist.id)
                therapist_ids.add(therapist.id)
                key = _therapist_signing_key(therapist)
                if key:
                    secrets.append(key)
        else:
            logger.debug("[DEBUG-RESOLVE] no session found for invitee_uri=%s", invitee_uri)

    logger.debug(
        "[DEBUG-RESOLVE] FINAL: matched_therapist_ids=%s, secrets_count=%d",
        therapist_ids, len(secrets),
    )

    # Preserve order while de-duplicating.
    return list(dict.fromkeys(secrets))


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

    Calendly webhook payload structure (invitee.created):
    {
        "scheduled_event": {
            "uri": "https://api.calendly.com/scheduled_events/XXXXX",
            "event_memberships": [
                {"user": "https://api.calendly.com/users/XXXXX"}
            ],
            ...
        },
        "event": "https://api.calendly.com/scheduled_events/XXXXX",
        "questions_and_answers": [
            {"question": "Phone Number", "answer": "+85212345678"}
        ],
        "name": "John Doe",
        "email": "patient@example.com",
        "uri": "https://api.calendly.com/scheduled_events/XXXXX/invitees/YYYYY"
    }
    """
    try:
        # Extract data from payload
        event_uri = _payload_uri(payload, "event", "new_event", "new_event_uri")
        invitee = payload.get("invitee", {})
        invitee_uri = _extract_uri(invitee) or _payload_uri(payload, "new_invitee", "new_invitee_uri")
        # Also try top-level uri (Calendly puts invitee URI there)
        if not invitee_uri:
            invitee_uri = _extract_uri(payload.get("uri"))
        old_event_uri = _payload_uri(payload, "old_event", "old_event_uri")
        old_invitee_uri = _payload_uri(payload, "old_invitee", "old_invitee_uri")
        is_rescheduled = bool(payload.get("rescheduled")) or bool(old_event_uri or old_invitee_uri)
        invitee_name = payload.get("name") or (invitee.get("name") if isinstance(invitee, dict) else None)
        questions_and_answers = payload.get("questions_and_answers", [])

        if not event_uri:
            logger.error("No event URI found in invitee.created payload")
            return {"status": "error", "message": "Missing event URI"}

        # Extract therapist's Calendly user URI from event memberships
        # Calendly nests event_memberships under scheduled_event
        scheduled_event = payload.get("scheduled_event", {})
        if isinstance(scheduled_event, dict):
            event_memberships = scheduled_event.get("event_memberships", [])
        else:
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
