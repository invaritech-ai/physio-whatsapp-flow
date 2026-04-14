"""Message logging service for WhatsApp messages."""

from datetime import datetime, timezone

from sqlmodel import Session

from app.models import MessageLog


def log_inbound(
    db: Session,
    phone_e164: str,
    body: str,
    twilio_sid: str | None,
    client_id: int | None,
    media_url: str | None = None,
) -> MessageLog:
    """Log an inbound WhatsApp message."""
    message = MessageLog(
        direction="inbound",
        phone_e164=phone_e164,
        body=body,
        media_url=media_url,
        twilio_sid=twilio_sid,
        client_id=client_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(message)
    # Avoid a full commit here; caller commits later in the same request.
    db.flush()
    return message


def log_outbound(
    db: Session,
    phone_e164: str,
    body: str,
    twilio_sid: str | None,
    client_id: int | None,
) -> MessageLog:
    """Log an outbound WhatsApp message."""
    message = MessageLog(
        direction="outbound",
        phone_e164=phone_e164,
        body=body,
        twilio_sid=twilio_sid,
        client_id=client_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
