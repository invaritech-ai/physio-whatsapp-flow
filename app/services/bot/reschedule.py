"""Reschedule/cancel helper - lookup upcoming sessions for client."""

from datetime import datetime, timezone
import logging

from sqlmodel import Session, select
from sqlmodel import func

from app.core.encryption import decrypt_string
from app.models import Session as TherapySession
from app.models import Therapist
from app.services.calendly import get_invitee_links_with_pat


logger = logging.getLogger(__name__)


def get_upcoming_sessions_with_links(db: Session, client_id: int | None) -> list[dict]:
    """
    Get all upcoming sessions for a client with reschedule/cancel URLs.

    Returns list of dicts with:
    - start_time: Formatted datetime string
    - therapist_name: Display name of therapist
    - reschedule_url: Client-facing Calendly reschedule link (if available)
    - cancel_url: Client-facing Calendly cancel link (if available)
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
        therapist = db.get(Therapist, session.therapist_id)
        therapist_name = therapist.display_name if therapist else "Unknown"

        # Format start time
        start_time_str = session.start_time.strftime("%A, %B %d at %I:%M %p")

        # Fetch true client-facing links from invitee resource.
        # Never expose raw Calendly API URIs to clients.
        reschedule_url = None
        cancel_url = None
        if session.calendly_invitee_uri and therapist and therapist.calendly_pat_encrypted:
            try:
                pat = decrypt_string(therapist.calendly_pat_encrypted)
                invitee_links = get_invitee_links_with_pat(session.calendly_invitee_uri, pat)
                if invitee_links:
                    reschedule_url = invitee_links.get("reschedule_url")
                    cancel_url = invitee_links.get("cancel_url")
            except Exception:
                logger.exception(
                    "Failed to resolve Calendly invitee links for session_id=%s therapist_id=%s",
                    session.id,
                    session.therapist_id,
                )

        result.append(
            {
                "start_time": start_time_str,
                "therapist_name": therapist_name,
                "reschedule_url": reschedule_url,
                "cancel_url": cancel_url,
            }
        )

    return result


def has_upcoming_sessions(db: Session, client_id: int | None) -> bool:
    """Return True when client has at least one scheduled future session."""
    if client_id is None:
        return False

    now = datetime.now(timezone.utc)
    count_stmt = select(func.count(TherapySession.id)).where(
        TherapySession.client_id == client_id,
        TherapySession.start_time > now,
        TherapySession.status == "scheduled",
    )
    return bool(db.exec(count_stmt).one())
