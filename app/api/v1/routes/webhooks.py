"""Webhook endpoints for external service integrations."""

import json
import hashlib
import hmac
import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlmodel import Session, select

from app.core.encryption import decrypt_string
from app.core.config import settings
from app.core.process_trace import (
    CHANNEL_CALENDLY_WEBHOOK,
    attach_trace_to_result,
    get_trace_id,
    new_trace_id,
    process_trace,
    reset_trace_id,
)
from app.db.session import get_session
from app.models import AuthEvent, Client, Session as TherapySession, SessionNote, Therapist, TherapistEventType
from app.services.booking_intents import (
    consume_booking_intent,
    find_recent_booking_intent,
    normalize_phone_e164,
)
from app.services.calendly import get_scheduled_event_with_pat
from app.services.bot.helpers import send_and_log
from app.services.timezone_utils import resolve_client_timezone, to_preferred_timezone

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

logger = logging.getLogger(__name__)

_EMAIL_SCRUB_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Avoid multi-megabyte log lines when DEBUG_MODE dumps full Calendly JSON.
_MAX_CALENDLY_TRACE_JSON_CHARS = 120_000


def _calendly_trace(stage: str, **fields: Any) -> None:
    process_trace(CHANNEL_CALENDLY_WEBHOOK, stage, **fields)


def _mask_phone_for_log(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 4:
        return f"***{digits[-4:]} (len={len(digits)})"
    return "***"


def _redact_nested_for_log(obj: Any, *, depth: int = 14, max_list: int = 120, max_str: int = 8000) -> Any:
    if depth <= 0:
        return "…"
    if isinstance(obj, str):
        scrubbed = _EMAIL_SCRUB_RE.sub("[email]", obj)
        if len(scrubbed) > max_str:
            return scrubbed[:max_str] + "…[truncated]"
        return scrubbed
    if isinstance(obj, dict):
        return {str(k): _redact_nested_for_log(v, depth=depth - 1, max_list=max_list, max_str=max_str) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_nested_for_log(v, depth=depth - 1, max_list=max_list, max_str=max_str) for v in obj[:max_list]]
    return obj


def _calendly_trace_full_envelope(label: str, data: dict[str, Any]) -> None:
    if not settings.debug_mode:
        return
    try:
        redacted = _redact_nested_for_log(data)
        raw = json.dumps(redacted, default=str)
        if len(raw) > _MAX_CALENDLY_TRACE_JSON_CHARS:
            raw = raw[:_MAX_CALENDLY_TRACE_JSON_CHARS] + "…[truncated]"
        _calendly_trace(label, redacted_envelope_json=raw)
    except Exception as exc:
        _calendly_trace(f"{label}_envelope_serialize_failed", error=str(exc))


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
    _, trace_token = new_trace_id()
    try:
        # Parse JSON payload before signature verification so we can resolve therapist
        # specific signing keys stored in database.
        logger.debug("[DEBUG-WH] === Incoming Calendly webhook ===")
        logger.debug("[DEBUG-WH] Calendly-Webhook-Signature header: %s", signature)
        try:
            body = await request.body()
            data = await request.json()
        except Exception as e:
            logger.error(f"Failed to parse webhook JSON: {e}")
            _calendly_trace("http_parse_error", error_type=type(e).__name__, error=str(e)[:400])
            raise HTTPException(status_code=400, detail="Invalid JSON")
        if not isinstance(data, dict):
            _calendly_trace("http_parse_error", reason="root_not_object", got_type=type(data).__name__)
            raise HTTPException(status_code=400, detail="Invalid JSON")

        event_type = data.get("event")
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        logger.debug("[DEBUG-WH] event_type=%s", event_type)
        logger.debug("[DEBUG-WH] payload keys=%s", list(payload.keys()) if payload else "empty")
        scheduled_event = payload.get("scheduled_event", {})
        logger.debug(
            "[DEBUG-WH] scheduled_event keys=%s",
            list(scheduled_event.keys()) if isinstance(scheduled_event, dict) else type(scheduled_event),
        )
        logger.debug(
            "[DEBUG-WH] event_memberships=%s",
            scheduled_event.get("event_memberships") if isinstance(scheduled_event, dict) else None,
        )
        logger.debug("[DEBUG-WH] raw body length=%d bytes", len(body))

        _calendly_trace(
            "http_received",
            path=str(request.url.path),
            client_host=getattr(request.client, "host", None),
            body_bytes=len(body),
            envelope_top_level_keys=sorted(data.keys()),
            webhook_event_field=event_type,
            payload_top_level_keys=sorted(payload.keys()) if payload else [],
            signature_header_present=bool(signature),
        )
        _calendly_trace_full_envelope("raw_webhook_envelope", data)

        secrets = _resolve_calendly_signing_secrets(db, payload)
        logger.debug("[DEBUG-WH] resolved %d signing secrets", len(secrets))
        sig_ok = verify_calendly_signature(body, signature, secrets)
        _calendly_trace(
            "signature_check",
            ok=sig_ok,
            secrets_tried=len(secrets),
            webhook_event_field=event_type,
        )
        if not sig_ok:
            logger.warning("Invalid Calendly webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

        logger.info(f"Received Calendly webhook: {event_type}")

        result = await process_calendly_event(db=db, event_type=event_type, payload=payload)
        if isinstance(result, dict):
            return attach_trace_to_result(result)
        return result
    finally:
        reset_trace_id(trace_token)


async def process_calendly_event(
    *,
    db: Session,
    event_type: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Process verified Calendly webhook payload by event type."""
    _calendly_trace("handler_dispatch", webhook_event_type=event_type)
    if event_type == "invitee.created":
        out = await handle_invitee_created(db, payload)
    elif event_type == "invitee.rescheduled":
        # Kept as a compatibility fallback. Current subscription setup relies on
        # invitee.created + invitee.canceled for reschedule flows.
        out = await handle_invitee_rescheduled(db, payload)
    elif event_type == "invitee.canceled":
        out = await handle_invitee_canceled(db, payload)
    else:
        logger.warning("Unhandled Calendly event type: %s", event_type)
        out = {"status": "ignored", "event": event_type}
    if isinstance(out, dict):
        _calendly_trace(
            "handler_return",
            webhook_event_type=event_type,
            result_status=out.get("status"),
            result_keys=sorted(out.keys()),
        )
        # Raise a loud, persisted alert whenever a verified webhook did NOT save a session,
        # so silent data loss (e.g. unmapped event type, missing PAT, fetch failure) can no
        # longer go unnoticed. Best-effort: never let alerting break webhook handling.
        if _is_dropped_booking(event_type, out):
            _record_dropped_booking_alert(
                db=db, event_type=event_type, payload=payload, result=out
            )
    return out


def _is_dropped_booking(event_type: str | None, result: dict[str, Any]) -> bool:
    """Decide whether a handler result represents a booking that should have saved but didn't."""
    status = result.get("status")
    if status == "success":
        return False
    if event_type in ("invitee.created", "invitee.rescheduled"):
        # A created/rescheduled event must always resolve to a saved/updated session.
        return status in ("error", "not_found")
    if event_type == "invitee.canceled":
        # "not_found" is expected for out-of-order or never-saved cancellations; only a
        # genuine processing error counts as a dropped booking here.
        return status == "error"
    return False


def _record_dropped_booking_alert(
    *,
    db: Session,
    event_type: str | None,
    payload: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Persist an admin alert (AuthEvent) when a verified Calendly webhook didn't save.

    Best-effort and idempotent: Calendly retries on the same booking won't create
    duplicate alerts. Never raises — alerting must not break webhook processing.
    """
    try:
        status = result.get("status")
        scheduled_event = payload.get("scheduled_event")
        event_uri = scheduled_event.get("uri") if isinstance(scheduled_event, dict) else None
        if not event_uri:
            event_uri = _payload_uri(
                payload, "event", "new_event", "new_event_uri", "old_event", "old_event_uri"
            )
        invitee_uri = _extract_uri(payload.get("uri")) or _payload_uri(
            payload, "invitee", "new_invitee", "new_invitee_uri", "old_invitee", "old_invitee_uri"
        )
        event_type_uri = (
            scheduled_event.get("event_type") if isinstance(scheduled_event, dict) else None
        )
        invitee_name = payload.get("name")
        if isinstance(invitee_name, str) and len(invitee_name) > 120:
            invitee_name = invitee_name[:120] + "…"

        reason = f"calendly_dropped:{invitee_uri or event_uri or 'unknown'}:{status}"
        existing = db.exec(
            select(AuthEvent).where(
                AuthEvent.event_type == "admin.calendly.dropped_booking",
                AuthEvent.reason == reason,
            )
        ).first()
        if existing:
            return

        details = {
            "webhook_event_type": event_type,
            "result_status": status,
            "result_message": result.get("message"),
            "calendly_event_uri": event_uri,
            "calendly_invitee_uri": invitee_uri,
            "calendly_event_type_uri": event_type_uri,
            "invitee_name": invitee_name,
            "trace_id": get_trace_id(),
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "alert_status": "new",
        }
        db.add(
            AuthEvent(
                event_type="admin.calendly.dropped_booking",
                reason=reason,
                details_json=json.dumps(details, default=str),
            )
        )
        db.commit()

        logger.error(
            "DROPPED BOOKING ALERT: webhook_event=%s status=%s message=%s "
            "event_uri=%s invitee_uri=%s event_type_uri=%s",
            event_type,
            status,
            result.get("message"),
            event_uri,
            invitee_uri,
            event_type_uri,
        )
        _calendly_trace(
            "dropped_booking_alert",
            webhook_event_type=event_type,
            result_status=status,
            calendly_event_uri=event_uri,
            calendly_invitee_uri=invitee_uri,
            calendly_event_type_uri=event_type_uri,
        )
    except Exception:
        logger.exception("Failed to record dropped-booking alert (event_type=%s)", event_type)
        try:
            db.rollback()
        except Exception:
            pass


def _format_local_timestamp(value: datetime, preferred_timezone: str | None) -> str:
    local_value = to_preferred_timezone(value, preferred_timezone)
    # Keep formatting portable by avoiding %-d / %-I.
    date_part = local_value.strftime("%a, %b %d, %Y")
    time_part = local_value.strftime("%I:%M %p").lstrip("0")
    return f"{date_part} {time_part}"


def _append_therapist_notification_event(
    *,
    db: Session,
    event_type: str,
    user_id: int,
    details: dict[str, Any],
    dedupe_reason: str | None = None,
) -> bool:
    """Append a therapist notification event, with optional idempotency guard."""
    if dedupe_reason:
        existing = db.exec(
            select(AuthEvent).where(
                AuthEvent.event_type == event_type,
                AuthEvent.user_id == user_id,
                AuthEvent.reason == dedupe_reason,
            )
        ).first()
        if existing:
            return False

    event = AuthEvent(
        event_type=event_type,
        user_id=user_id,
        reason=dedupe_reason,
        details_json=json.dumps(details, default=str),
    )
    db.add(event)
    return True


def _notify_therapist_session_update(
    *,
    db: Session,
    session: TherapySession,
    therapist: Therapist,
    client: Client | None,
    event_type: str,
    action: str,
) -> None:
    """Create therapist app notification for session state changes."""
    local_start_text = _format_local_timestamp(session.start_time, therapist.preferred_timezone)
    details = {
        "session_id": session.id,
        "client_id": client.id if client else session.client_id,
        "client_name": client.name if client else None,
        "therapist_name": therapist.display_name,
        "status": session.status,
        "start_time_utc": session.start_time.isoformat(),
        "start_time_local": local_start_text,
        "timezone": therapist.preferred_timezone or settings.invoice_timezone or "UTC",
        "duration_minutes": session.duration_minutes,
        "action": action,
    }
    dedupe_reason = f"session:{session.id}:{action}"
    created = _append_therapist_notification_event(
        db=db,
        event_type=event_type,
        user_id=therapist.user_id,
        details=details,
        dedupe_reason=dedupe_reason,
    )
    if created:
        db.commit()


_CALENDLY_OPERATIONAL_EVENT_MAP = {
    "invitee.created": (
        "admin.calendly.queue.invitee.created",
        "therapist.calendly.feed.created",
        "created",
    ),
    "invitee.canceled": (
        "admin.calendly.queue.invitee.canceled",
        "therapist.calendly.feed.canceled",
        "canceled",
    ),
    "invitee.rescheduled": (
        "admin.calendly.queue.invitee.rescheduled",
        "therapist.calendly.feed.rescheduled",
        "rescheduled",
    ),
}


def _append_calendly_operational_events(
    *,
    db: Session,
    webhook_event_type: str,
    session: TherapySession,
    therapist: Therapist,
    client: Client | None,
) -> None:
    """Write admin queue + therapist feed rows for Calendly workflow observability."""
    mapped = _CALENDLY_OPERATIONAL_EVENT_MAP.get(webhook_event_type)
    if not mapped:
        return

    admin_event_type, therapist_event_type, action = mapped
    reason = f"session:{session.id}:calendly:{action}"

    base_details: dict[str, Any] = {
        "session_id": session.id,
        "calendly_event_uri": session.calendly_event_uri,
        "calendly_invitee_uri": session.calendly_invitee_uri,
        "client_id": client.id if client else session.client_id,
        "client_name": client.name if client else None,
        "therapist_id": therapist.id,
        "therapist_name": therapist.display_name,
        "start_time_utc": session.start_time.isoformat(),
        "end_time_utc": session.end_time.isoformat(),
        "duration_minutes": session.duration_minutes,
        "session_status": session.status,
    }

    wrote_any = False

    existing_admin = db.exec(
        select(AuthEvent).where(
            AuthEvent.event_type == admin_event_type,
            AuthEvent.reason == reason,
        )
    ).first()
    if not existing_admin:
        admin_details = {
            **base_details,
            "queue_status": "new",
            "queue_updated_at": datetime.now(timezone.utc).isoformat(),
        }
        db.add(
            AuthEvent(
                event_type=admin_event_type,
                reason=reason,
                details_json=json.dumps(admin_details, default=str),
            )
        )
        wrote_any = True

    existing_feed = db.exec(
        select(AuthEvent).where(
            AuthEvent.event_type == therapist_event_type,
            AuthEvent.user_id == therapist.user_id,
            AuthEvent.reason == reason,
        )
    ).first()
    if not existing_feed:
        therapist_details = {
            **base_details,
            "feed_status": "new",
            "feed_updated_at": datetime.now(timezone.utc).isoformat(),
        }
        db.add(
            AuthEvent(
                event_type=therapist_event_type,
                user_id=therapist.user_id,
                reason=reason,
                details_json=json.dumps(therapist_details, default=str),
            )
        )
        wrote_any = True

    if wrote_any:
        db.commit()


def _notify_booking_confirmed(
    *,
    db: Session,
    session: TherapySession,
    client: Client,
    therapist: Therapist,
) -> None:
    """
    Send booking-confirmed notifications.

    - Client: WhatsApp confirmation message (idempotent via session.reminder_sent).
    - Therapist: in-app notification row (idempotent via session.therapist_notified).
    """
    dirty = False
    local_start_text = _format_local_timestamp(session.start_time, therapist.preferred_timezone)
    therapist_tz = therapist.preferred_timezone or settings.invoice_timezone or "UTC"
    # Client-facing times use the client's timezone (inferred from their phone
    # country code), so a client in India isn't shown an unlabeled HK time.
    client_tz = resolve_client_timezone(client.phone_e164, therapist.preferred_timezone)

    if not session.reminder_sent:
        try:
            client_name = client.name or "there"
            template_sid = (settings.twilio_whatsapp_session_booked_content_sid or "").strip()
            if template_sid:
                local_dt = to_preferred_timezone(session.start_time, client_tz)
                date_str = local_dt.strftime("%a, %b %d, %Y")
                time_str = local_dt.strftime("%I:%M %p").lstrip("0")
                tz_abbrev = local_dt.strftime("%Z")
                if tz_abbrev:
                    time_str = f"{time_str} ({tz_abbrev})"
                send_and_log(
                    db=db,
                    phone_e164=client.phone_e164,
                    body=None,
                    client_id=client.id,
                    content_sid=template_sid,
                    content_variables={
                        "1": client_name,
                        "2": therapist.display_name or "",
                        "3": date_str,
                        "4": time_str,
                        "5": str(session.duration_minutes),
                    },
                )
            else:
                client_local_dt = to_preferred_timezone(session.start_time, client_tz)
                client_local_text = _format_local_timestamp(session.start_time, client_tz)
                tz_label = client_local_dt.strftime("%Z") or client_tz
                message = (
                    f"Booking confirmed, {client_name}! ✅\n\n"
                    f"Therapist: {therapist.display_name}\n"
                    f"Time: {client_local_text} ({tz_label})\n\n"
                    "If you need to reschedule or cancel, reply with 'reschedule'."
                )
                send_and_log(
                    db=db,
                    phone_e164=client.phone_e164,
                    body=message,
                    client_id=client.id,
                )
            session.reminder_sent = True
            dirty = True
        except Exception:
            logger.exception(
                "Failed to send client booking confirmation session_id=%s client_id=%s",
                session.id,
                client.id,
            )

    if not session.therapist_notified:
        details = {
            "session_id": session.id,
            "client_id": client.id,
            "client_name": client.name,
            "therapist_name": therapist.display_name,
            "start_time_utc": session.start_time.isoformat(),
            "start_time_local": local_start_text,
            "timezone": therapist_tz,
            "duration_minutes": session.duration_minutes,
        }
        _append_therapist_notification_event(
            db=db,
            event_type="therapist.notification.booking_confirmed",
            user_id=therapist.user_id,
            details=details,
            dedupe_reason=f"session:{session.id}:booking_confirmed",
        )
        session.therapist_notified = True
        dirty = True

    if dirty:
        session.updated_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()


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

    _calendly_trace(
        "signing_secrets_resolved",
        matched_therapist_ids=sorted(therapist_ids),
        unique_secrets_count=len(list(dict.fromkeys(secrets))),
    )

    # Preserve order while de-duplicating.
    return list(dict.fromkeys(secrets))


def _find_session_by_refs(
    db: Session,
    *,
    event_uri: str | None = None,
    invitee_uri: str | None = None,
) -> TherapySession | None:
    # Prefer invitee_uri (unique per booking) over event_uri (unique per scheduled event)
    if invitee_uri:
        session = db.exec(
            select(TherapySession).where(TherapySession.calendly_invitee_uri == invitee_uri)
        ).first()
        if session:
            return session

    if event_uri:
        session = db.exec(
            select(TherapySession).where(TherapySession.calendly_event_uri == event_uri)
        ).first()
        if session:
            return session

    return None


def _seed_session_note_from_previous_session(
    db: Session,
    *,
    session_row: TherapySession,
    therapist_user_id: int,
) -> None:
    """Create initial note for a new session by copying the previous session note.

    If no prior session-note exists for this therapist+client chain, seed with empty text.
    """
    if session_row.id is None:
        return

    previous_session = db.exec(
        select(TherapySession)
        .where(
            TherapySession.client_id == session_row.client_id,
            TherapySession.therapist_id == session_row.therapist_id,
            TherapySession.id != session_row.id,
            TherapySession.start_time <= session_row.start_time,
        )
        .order_by(TherapySession.start_time.desc(), TherapySession.id.desc())
    ).first()

    note_text = ""
    previous_session_id: int | None = None
    copied_from_previous = False
    if previous_session is not None:
        previous_session_id = previous_session.id
        previous_note = db.exec(
            select(SessionNote)
            .where(
                SessionNote.session_id == previous_session.id,
                SessionNote.author_user_id == therapist_user_id,
            )
            .order_by(SessionNote.created_at.desc())
        ).first()
        if previous_note is not None:
            note_text = previous_note.note_text or ""
            copied_from_previous = True

    db.add(
        SessionNote(
            session_id=session_row.id,
            author_user_id=therapist_user_id,
            note_text=note_text,
        )
    )
    _calendly_trace(
        "invitee_created_note_seeded",
        session_id=session_row.id,
        previous_session_id=previous_session_id,
        copied_from_previous=copied_from_previous,
        note_chars=len(note_text),
    )


def _get_active_event_type_mappings(
    db: Session,
    *,
    therapist_id: int,
    event_type_uri: str,
) -> list[TherapistEventType]:
    return db.exec(
        select(TherapistEventType).where(
            TherapistEventType.therapist_id == therapist_id,
            TherapistEventType.calendly_event_type_uri == event_type_uri,
            TherapistEventType.is_active == True,  # noqa: E712
        )
    ).all()


def _resolve_session_duration_minutes(
    db: Session,
    *,
    therapist: Therapist,
    event_type_uri: str,
    client_phone_e164: str | None,
    existing_session: TherapySession | None,
    scheduled_duration_minutes: int | None = None,
) -> int | None:
    if client_phone_e164:
        intent = find_recent_booking_intent(
            db,
            therapist_id=therapist.id,
            client_phone_e164=client_phone_e164,
            calendly_event_type_uri=event_type_uri,
        )
        if intent:
            consume_booking_intent(intent)
            db.add(intent)
            return intent.duration_minutes

    matches = _get_active_event_type_mappings(
        db,
        therapist_id=therapist.id,
        event_type_uri=event_type_uri,
    )
    if len(matches) == 1:
        return matches[0].duration_minutes

    # Shared URI: same event type mapped to multiple durations (e.g. 30-min and 45-min).
    # Use the actual scheduled duration from the Calendly event as a tiebreaker.
    if len(matches) > 1 and scheduled_duration_minutes is not None:
        for match in matches:
            if match.duration_minutes == scheduled_duration_minutes:
                return match.duration_minutes
        # Duration not in mapping — trust what Calendly actually scheduled.
        logger.warning(
            "Shared URI tiebreaker: scheduled_duration=%s not in mapping durations=%s for therapist_id=%s; using scheduled duration",
            scheduled_duration_minutes,
            [m.duration_minutes for m in matches],
            therapist.id,
        )
        return scheduled_duration_minutes

    if existing_session:
        return existing_session.duration_minutes

    # Defensive fallback: no booking intent, no mapping, and no existing session to inherit
    # from — but Calendly already told us the actual scheduled length. Trust it instead of
    # silently dropping the booking. This guards against unmapped event types (e.g. a
    # duplicate-named "Movement" event created by an external booking/migration tool that
    # was never registered in therapisteventtype).
    if scheduled_duration_minutes is not None:
        logger.warning(
            "No TherapistEventType mapping for therapist_id=%s event_type_uri=%s (matches=%s); "
            "falling back to Calendly scheduled duration=%smin",
            therapist.id,
            event_type_uri,
            len(matches),
            scheduled_duration_minutes,
        )
        _calendly_trace(
            "invitee_created_duration_fallback",
            therapist_id=therapist.id,
            calendly_event_type_uri=event_type_uri,
            scheduled_duration_minutes=scheduled_duration_minutes,
            mapping_matches=len(matches),
        )
        return scheduled_duration_minutes

    logger.error(
        "Cannot resolve session duration therapist_id=%s event_type_uri=%s matches=%s "
        "and no Calendly scheduled duration available",
        therapist.id,
        event_type_uri,
        len(matches),
    )
    return None


def _extract_phone_from_questions_and_answers(questions_and_answers: object) -> str | None:
    if not isinstance(questions_and_answers, list):
        return None

    def looks_like_phone_answer(value: str) -> bool:
        text = value.strip()
        if not text:
            return False
        # Allow common phone formatting chars, reject obvious non-phone text.
        if re.search(r"[A-Za-z]", text):
            return False
        digits = re.sub(r"\D", "", text)
        return 7 <= len(digits) <= 15

    # Priority: whatsapp -> phone -> number
    keyword_tiers = ("whatsapp", "phone", "number")

    for keyword in keyword_tiers:
        for qa in questions_and_answers:
            if not isinstance(qa, dict):
                continue
            question = str(qa.get("question", "")).lower()
            answer = str(qa.get("answer", "")).strip()
            if keyword in question and looks_like_phone_answer(answer):
                return answer

    return None


def _summarize_qa_for_trace(questions_and_answers: object) -> list[dict[str, Any]]:
    if not isinstance(questions_and_answers, list):
        return []
    rows: list[dict[str, Any]] = []
    for qa in questions_and_answers:
        if not isinstance(qa, dict):
            continue
        q = str(qa.get("question", ""))[:200]
        a = qa.get("answer")
        rows.append({"question": q, "answer_masked": _mask_phone_for_log(str(a) if a is not None else "")})
    return rows


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
        # Prefer scheduled_event.uri (canonical) over payload.event
        scheduled_event = payload.get("scheduled_event", {})
        event_uri = scheduled_event.get("uri") if isinstance(scheduled_event, dict) else None
        if not event_uri:
            event_uri = _payload_uri(payload, "event", "new_event", "new_event_uri")
        # Invitee URI: payload.uri is canonical for Calendly v2
        invitee = payload.get("invitee", {})
        invitee_uri = _extract_uri(payload.get("uri"))
        if not invitee_uri:
            invitee_uri = _extract_uri(invitee) or _payload_uri(payload, "new_invitee", "new_invitee_uri")
        old_event_uri = _payload_uri(payload, "old_event", "old_event_uri")
        old_invitee_uri = _payload_uri(payload, "old_invitee", "old_invitee_uri")
        is_rescheduled = bool(payload.get("rescheduled")) or bool(old_event_uri or old_invitee_uri)
        invitee_name = payload.get("name") or (invitee.get("name") if isinstance(invitee, dict) else None)
        questions_and_answers = payload.get("questions_and_answers", [])

        _name_hint: str | None = invitee_name if isinstance(invitee_name, str) else None
        if _name_hint and len(_name_hint) > 80:
            _name_hint = _name_hint[:80] + "…"
        _calendly_trace(
            "invitee_created_start",
            event_uri=event_uri,
            invitee_uri=invitee_uri,
            old_event_uri=old_event_uri,
            old_invitee_uri=old_invitee_uri,
            is_rescheduled=is_rescheduled,
            invitee_name_hint=_name_hint,
            questions_and_answers_summary=_summarize_qa_for_trace(questions_and_answers),
        )

        if not event_uri:
            logger.error("No event URI found in invitee.created payload")
            _calendly_trace("invitee_created_error", reason="missing_event_uri")
            return {"status": "error", "message": "Missing event URI"}

        # Extract therapist's Calendly user URI from event memberships
        # Calendly nests event_memberships under scheduled_event
        scheduled_event = payload.get("scheduled_event", {})
        if isinstance(scheduled_event, dict):
            event_memberships = scheduled_event.get("event_memberships") or []
        else:
            event_memberships = []
        if not event_memberships:
            event_memberships = payload.get("event_memberships") or []
        if not event_memberships:
            logger.error("No event_memberships in webhook payload")
            _calendly_trace("invitee_created_error", reason="missing_event_memberships")
            return {"status": "error", "message": "Missing event memberships"}

        therapist_calendly_uri = event_memberships[0].get("user")

        # Look up therapist by Calendly user URI
        therapist = db.exec(
            select(Therapist).where(Therapist.calendly_user_uri == therapist_calendly_uri)
        ).first()

        if not therapist:
            logger.error(f"No therapist found for Calendly user: {therapist_calendly_uri}")
            _calendly_trace(
                "invitee_created_error",
                reason="therapist_not_found",
                therapist_calendly_user_uri=therapist_calendly_uri,
                membership_count=len(event_memberships),
            )
            return {"status": "error", "message": "Therapist not found"}

        _calendly_trace(
            "invitee_created_therapist_resolved",
            therapist_id=therapist.id,
            therapist_calendly_user_uri=therapist.calendly_user_uri,
            has_pat=bool(therapist.calendly_pat_encrypted),
            has_stored_signing_key=bool(therapist.calendly_webhook_signing_key_encrypted),
        )

        # Fetch scheduled event details via therapist's PAT
        if not therapist.calendly_pat_encrypted:
            logger.error(f"Therapist {therapist.id} has no Calendly PAT")
            _calendly_trace("invitee_created_error", reason="missing_pat", therapist_id=therapist.id)
            return {"status": "error", "message": "Therapist PAT not configured"}

        pat = decrypt_string(therapist.calendly_pat_encrypted)
        event_details = get_scheduled_event_with_pat(event_uri, pat)

        if not event_details:
            logger.error(f"Failed to fetch scheduled event details: {event_uri}")
            _calendly_trace(
                "invitee_created_error",
                reason="scheduled_event_fetch_failed",
                therapist_id=therapist.id,
                event_uri=event_uri,
            )
            return {"status": "error", "message": "Could not fetch event details"}

        # Parse start/end times
        start_time = datetime.fromisoformat(
            event_details["start_time"].replace("Z", "+00:00")
        )
        end_time = datetime.fromisoformat(
            event_details["end_time"].replace("Z", "+00:00")
        )

        event_type_uri = event_details["event_type"]

        _calendly_trace(
            "invitee_created_scheduled_event_fetched",
            therapist_id=therapist.id,
            event_uri=event_uri,
            calendly_event_type_uri=event_type_uri,
            start_time=event_details.get("start_time"),
            end_time=event_details.get("end_time"),
            api_status=event_details.get("status"),
        )

        # Extract phone number from custom questions.
        # Priority order: labels containing whatsapp -> phone -> number.
        phone_number = _extract_phone_from_questions_and_answers(questions_and_answers)

        if not phone_number:
            logger.error("No phone number found in booking form")
            _calendly_trace(
                "invitee_created_error",
                reason="phone_not_found_in_qa",
                therapist_id=therapist.id,
                questions_and_answers_summary=_summarize_qa_for_trace(questions_and_answers),
            )
            return {"status": "error", "message": "Phone number required"}

        # Normalize phone number: strip whatsapp: prefix, remove spaces/dashes, ensure E.164
        phone_e164 = normalize_phone_e164(phone_number)
        _calendly_trace(
            "invitee_created_phone_extracted",
            therapist_id=therapist.id,
            raw_phone_masked=_mask_phone_for_log(phone_number),
            normalized_phone_masked=_mask_phone_for_log(phone_e164),
        )

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

        scheduled_duration_minutes = int((end_time - start_time).total_seconds() // 60)
        duration_minutes = _resolve_session_duration_minutes(
            db,
            therapist=therapist,
            event_type_uri=event_type_uri,
            client_phone_e164=phone_e164,
            existing_session=session,
            scheduled_duration_minutes=scheduled_duration_minutes,
        )
        if duration_minutes is None:
            _calendly_trace(
                "invitee_created_error",
                reason="ambiguous_event_type_mapping",
                therapist_id=therapist.id,
                calendly_event_type_uri=event_type_uri,
                scheduled_duration_minutes=scheduled_duration_minutes,
                had_existing_session=session is not None,
            )
            return {"status": "error", "message": "Ambiguous event type mapping"}

        _calendly_trace(
            "invitee_created_duration_resolved",
            therapist_id=therapist.id,
            duration_minutes=duration_minutes,
            scheduled_duration_minutes=scheduled_duration_minutes,
            calendly_event_type_uri=event_type_uri,
            session_match_mode="update" if session else "create",
        )

        if session:
            previous_event_uri = session.calendly_event_uri
            session.client_id = client.id
            session.therapist_id = therapist.id
            session.start_time = start_time
            session.end_time = end_time
            session.duration_minutes = duration_minutes
            session.calendly_event_uri = event_uri
            if invitee_uri:
                session.calendly_invitee_uri = invitee_uri
            session.source = "calendly"
            session.status = "scheduled"
            if previous_event_uri != event_uri:
                # Re-notify on a newly confirmed event after reschedule/rebook changes.
                session.reminder_sent = False
                session.therapist_notified = False
            session.updated_at = datetime.now(timezone.utc)
            db.add(session)
            db.commit()
            db.refresh(session)

            logger.info(
                "Updated existing session %s via invitee.created (rescheduled=%s)",
                session.id,
                is_rescheduled,
            )
            _calendly_trace(
                "invitee_created_session_updated",
                session_id=session.id,
                client_id=client.id,
                therapist_id=therapist.id,
                is_rescheduled=is_rescheduled,
            )
        else:
            session = TherapySession(
                client_id=client.id,
                therapist_id=therapist.id,
                start_time=start_time,
                end_time=end_time,
                duration_minutes=duration_minutes,
                calendly_event_uri=event_uri,
                calendly_invitee_uri=invitee_uri,
                source="calendly",
                status="scheduled",
            )
            db.add(session)
            db.flush()
            _seed_session_note_from_previous_session(
                db,
                session_row=session,
                therapist_user_id=therapist.user_id,
            )
            db.commit()
            db.refresh(session)

            logger.info(
                f"Created session {session.id} for client {client.id} "
                f"with therapist {therapist.id} (duration: {session.duration_minutes}min)"
            )
            _calendly_trace(
                "invitee_created_session_created",
                session_id=session.id,
                client_id=client.id,
                therapist_id=therapist.id,
            )

        # Best-effort notifications (idempotent).
        _notify_booking_confirmed(
            db=db,
            session=session,
            client=client,
            therapist=therapist,
        )
        try:
            _append_calendly_operational_events(
                db=db,
                webhook_event_type="invitee.rescheduled" if is_rescheduled else "invitee.created",
                session=session,
                therapist=therapist,
                client=client,
            )
        except Exception:
            logger.exception(
                "Failed to append Calendly operational events session_id=%s therapist_id=%s",
                session.id,
                therapist.id,
            )

        out = {
            "status": "success",
            "session_id": session.id,
            "client_id": client.id,
            "therapist_id": therapist.id,
        }
        _calendly_trace("invitee_created_success", **{k: v for k, v in out.items() if k != "status"})
        return out

    except Exception as e:
        logger.exception(f"Error handling invitee.created event: {e}")
        db.rollback()
        _calendly_trace("invitee_created_exception", error_type=type(e).__name__, error=str(e)[:500])
        return {"status": "error", "message": str(e)}


async def handle_invitee_canceled(db: Session, payload: dict) -> dict:
    """Handle invitee.canceled event - mark session as canceled.

    Calendly fires invitee.canceled for both true cancellations and reschedules.
    We still process cancellation so out-of-order deliveries stay deterministic.
    The companion invitee.created webhook can move the same session back to
    scheduled with new event/invitee URIs.
    """
    try:
        _calendly_trace(
            "invitee_canceled_start",
            payload_rescheduled_flag=bool(payload.get("rescheduled")),
            payload_keys=sorted(payload.keys()),
        )
        if payload.get("rescheduled"):
            logger.info(
                "Processing invitee.canceled with rescheduled=True; invitee.created may re-activate updated session"
            )

        # Extract event URI from scheduled_event.uri (canonical) or payload.event
        scheduled_event = payload.get("scheduled_event")
        if isinstance(scheduled_event, dict):
            event_uri = scheduled_event.get("uri")
        else:
            event_uri = None
        if not event_uri:
            event_uri = _payload_uri(payload, "event", "old_event", "old_event_uri")

        # Extract invitee URI from payload.uri (canonical for cancel payloads)
        invitee_uri = _extract_uri(payload.get("uri"))
        if not invitee_uri:
            invitee_uri = _payload_uri(payload, "invitee", "old_invitee", "old_invitee_uri")

        logger.info(
            "Processing invitee.canceled: event_uri=%s, invitee_uri=%s",
            event_uri, invitee_uri,
        )
        _calendly_trace("invitee_canceled_refs", event_uri=event_uri, invitee_uri=invitee_uri)

        # Prefer invitee_uri match (more specific) over event_uri
        session = _find_session_by_refs(db, invitee_uri=invitee_uri, event_uri=event_uri)

        if not session:
            logger.warning(f"No session found for canceled event: {event_uri or invitee_uri}")
            _calendly_trace("invitee_canceled_not_found", event_uri=event_uri, invitee_uri=invitee_uri)
            return {"status": "not_found", "message": "Session not found"}

        # Update session status
        session.status = "cancelled"
        session.updated_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()

        therapist = db.get(Therapist, session.therapist_id)
        client = db.get(Client, session.client_id) if session.client_id else None
        if therapist:
            try:
                _notify_therapist_session_update(
                    db=db,
                    session=session,
                    therapist=therapist,
                    client=client,
                    event_type="therapist.notification.booking_cancelled",
                    action="cancelled",
                )
            except Exception:
                logger.exception(
                    "Failed to create therapist cancellation notification session_id=%s therapist_id=%s",
                    session.id,
                    therapist.id,
                )
            try:
                _append_calendly_operational_events(
                    db=db,
                    webhook_event_type="invitee.canceled",
                    session=session,
                    therapist=therapist,
                    client=client,
                )
            except Exception:
                logger.exception(
                    "Failed to append Calendly cancel operational events session_id=%s therapist_id=%s",
                    session.id,
                    therapist.id,
                )

        logger.info(f"Marked session {session.id} as cancelled")

        _calendly_trace("invitee_canceled_success", session_id=session.id, therapist_id=session.therapist_id)
        return {
            "status": "success",
            "session_id": session.id,
            "action": "canceled",
        }

    except Exception as e:
        logger.exception(f"Error handling invitee.canceled event: {e}")
        db.rollback()
        _calendly_trace("invitee_canceled_exception", error_type=type(e).__name__, error=str(e)[:500])
        return {"status": "error", "message": str(e)}


async def handle_invitee_rescheduled(db: Session, payload: dict) -> dict:
    """Handle invitee.rescheduled event - move/update existing session to new time."""
    try:
        old_event_uri = _payload_uri(payload, "old_event", "old_event_uri")
        new_event_uri = _payload_uri(payload, "new_event", "new_event_uri", "event")
        old_invitee_uri = _payload_uri(payload, "old_invitee", "old_invitee_uri")
        new_invitee_uri = _payload_uri(payload, "new_invitee", "new_invitee_uri", "invitee")

        _calendly_trace(
            "invitee_rescheduled_start",
            old_event_uri=old_event_uri,
            new_event_uri=new_event_uri,
            old_invitee_uri=old_invitee_uri,
            new_invitee_uri=new_invitee_uri,
            payload_keys=sorted(payload.keys()),
        )

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
            _calendly_trace(
                "invitee_rescheduled_not_found",
                old_event_uri=old_event_uri,
                old_invitee_uri=old_invitee_uri,
                new_event_uri=new_event_uri,
                new_invitee_uri=new_invitee_uri,
            )
            return {"status": "not_found", "message": "Session not found"}

        therapist = db.get(Therapist, session.therapist_id)
        if not therapist:
            logger.error(f"No therapist found for session {session.id}")
            _calendly_trace("invitee_rescheduled_error", reason="therapist_missing", session_id=session.id)
            return {"status": "error", "message": "Therapist not found"}

        if not therapist.calendly_pat_encrypted:
            logger.error(f"Therapist {therapist.id} has no Calendly PAT")
            _calendly_trace("invitee_rescheduled_error", reason="missing_pat", therapist_id=therapist.id)
            return {"status": "error", "message": "Therapist PAT not configured"}

        target_event_uri = new_event_uri or session.calendly_event_uri
        if not target_event_uri:
            logger.error(f"No target event URI in rescheduled payload for session {session.id}")
            _calendly_trace("invitee_rescheduled_error", reason="missing_target_event_uri", session_id=session.id)
            return {"status": "error", "message": "Missing event URI"}

        pat = decrypt_string(therapist.calendly_pat_encrypted)
        event_details = get_scheduled_event_with_pat(target_event_uri, pat)
        if not event_details:
            logger.error(f"Failed to fetch scheduled event details for reschedule: {target_event_uri}")
            _calendly_trace(
                "invitee_rescheduled_error",
                reason="scheduled_event_fetch_failed",
                target_event_uri=target_event_uri,
                therapist_id=therapist.id,
            )
            return {"status": "error", "message": "Could not fetch event details"}

        start_time = datetime.fromisoformat(
            event_details["start_time"].replace("Z", "+00:00")
        )
        end_time = datetime.fromisoformat(
            event_details["end_time"].replace("Z", "+00:00")
        )
        event_type_uri = event_details["event_type"]

        client_phone_e164 = None
        if session.client_id:
            client = db.get(Client, session.client_id)
            if client and client.phone_e164:
                client_phone_e164 = client.phone_e164

        scheduled_duration_minutes = int((end_time - start_time).total_seconds() // 60)
        resolved_duration = _resolve_session_duration_minutes(
            db,
            therapist=therapist,
            event_type_uri=event_type_uri,
            client_phone_e164=client_phone_e164,
            existing_session=session,
            scheduled_duration_minutes=scheduled_duration_minutes,
        )
        duration_minutes = resolved_duration if resolved_duration is not None else session.duration_minutes

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

            client = db.get(Client, existing_new_session.client_id)
            try:
                _notify_therapist_session_update(
                    db=db,
                    session=existing_new_session,
                    therapist=therapist,
                    client=client,
                    event_type="therapist.notification.booking_rescheduled",
                    action="rescheduled",
                )
            except Exception:
                logger.exception(
                    "Failed to create therapist reschedule notification session_id=%s therapist_id=%s",
                    existing_new_session.id,
                    therapist.id,
                )
            try:
                _append_calendly_operational_events(
                    db=db,
                    webhook_event_type="invitee.rescheduled",
                    session=existing_new_session,
                    therapist=therapist,
                    client=client,
                )
            except Exception:
                logger.exception(
                    "Failed to append Calendly reschedule operational events session_id=%s therapist_id=%s",
                    existing_new_session.id,
                    therapist.id,
                )

            logger.info(
                "Rescheduled session merged: old_session=%s new_session=%s",
                session.id,
                existing_new_session.id,
            )
            _calendly_trace(
                "invitee_rescheduled_success_merged",
                old_session_id=session.id,
                canonical_session_id=existing_new_session.id,
                therapist_id=therapist.id,
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

        client = db.get(Client, session.client_id)
        try:
            _notify_therapist_session_update(
                db=db,
                session=session,
                therapist=therapist,
                client=client,
                event_type="therapist.notification.booking_rescheduled",
                action="rescheduled",
            )
        except Exception:
            logger.exception(
                "Failed to create therapist reschedule notification session_id=%s therapist_id=%s",
                session.id,
                therapist.id,
            )
        try:
            _append_calendly_operational_events(
                db=db,
                webhook_event_type="invitee.rescheduled",
                session=session,
                therapist=therapist,
                client=client,
            )
        except Exception:
            logger.exception(
                "Failed to append Calendly reschedule operational events session_id=%s therapist_id=%s",
                session.id,
                therapist.id,
            )

        logger.info("Rescheduled session %s to event %s", session.id, target_event_uri)
        _calendly_trace(
            "invitee_rescheduled_success",
            session_id=session.id,
            therapist_id=therapist.id,
            target_event_uri=target_event_uri,
        )
        return {
            "status": "success",
            "session_id": session.id,
            "action": "rescheduled",
        }

    except Exception as e:
        logger.exception(f"Error handling invitee.rescheduled event: {e}")
        db.rollback()
        _calendly_trace("invitee_rescheduled_exception", error_type=type(e).__name__, error=str(e)[:500])
        return {"status": "error", "message": str(e)}
