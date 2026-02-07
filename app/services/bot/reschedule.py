"""Reschedule/cancel helper - lookup upcoming sessions for client."""

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models import Session as TherapySession


def get_upcoming_sessions_with_links(db: Session, client_id: int | None) -> list[dict]:
    """
    Get all upcoming sessions for a client with reschedule/cancel URLs.

    Returns list of dicts with:
    - start_time: Formatted datetime string
    - therapist_name: Display name of therapist
    - reschedule_url: Link to reschedule (stub in Phase 2)
    - cancel_url: Link to cancel (stub in Phase 2)
    """
    if client_id is None:
        return []

    # Query upcoming sessions
    now = datetime.now(timezone.utc)
    stmt = (
        select(TherapySession)
        .where(
            TherapySession.client_id == client_id,
            TherapySession.start_time > now,
            TherapySession.status == "scheduled",
        )
        .order_by(TherapySession.start_time)
    )

    sessions = db.exec(stmt).all()

    result = []
    for session in sessions:
        # Get therapist name
        therapist_name = (
            session.therapist.display_name if session.therapist else "Unknown"
        )

        # Format start time
        start_time_str = session.start_time.strftime("%A, %B %d at %I:%M %p")

        # STUB: Generate reschedule/cancel URLs
        # In Phase 3, this will use actual Calendly invitee URIs
        # For now, generate stub URLs based on event URI
        if session.calendly_event_uri:
            # In Phase 3, we'll use: session.calendly_invitee_uri + "/reschedule"
            reschedule_url = f"{session.calendly_event_uri}/reschedule"
            cancel_url = f"{session.calendly_event_uri}/cancel"
        else:
            # Fallback stub URLs
            reschedule_url = f"https://calendly.com/reschedule/stub-{session.id}"
            cancel_url = f"https://calendly.com/cancel/stub-{session.id}"

        result.append(
            {
                "start_time": start_time_str,
                "therapist_name": therapist_name,
                "reschedule_url": reschedule_url,
                "cancel_url": cancel_url,
            }
        )

    return result
