"""Seed a scheduled TherapySession for manual testing of the WhatsApp 24h
reschedule/cancel ban.

Usage (venv active, run from repo root):
    python scripts/seed_test_session.py <phone_e164> <hours_from_now>

Examples:
    python scripts/seed_test_session.py +9170XXXXXXXX 12   # <24h  -> ban (contact admin)
    python scripts/seed_test_session.py +9170XXXXXXXX 48   # >24h  -> shows links/help

Then message the bot from that number with:  reschedule
"""
import sys
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, create_engine, select

from app.core.config import settings
from app.models import Client, Therapist, Session as TherapySession


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    phone = sys.argv[1].strip()
    hours = float(sys.argv[2])

    eng = create_engine(settings.database_url)
    with Session(eng) as db:
        client = db.exec(select(Client).where(Client.phone_e164 == phone)).first()
        if not client:
            sys.exit(
                f"No client with phone {phone!r}. Message the bot once from that "
                f"number first so a client row is created, then re-run."
            )

        therapist = db.exec(
            select(Therapist).where(Therapist.is_active == True)  # noqa: E712
        ).first()
        if not therapist:
            sys.exit("No active therapist found to attach the session to.")

        start = datetime.now(timezone.utc) + timedelta(hours=hours)
        duration = 45
        row = TherapySession(
            client_id=client.id,
            therapist_id=therapist.id,
            start_time=start,
            end_time=start + timedelta(minutes=duration),
            duration_minutes=duration,
            status="scheduled",
            source="manual",
            currency="HKD",
            charge_amount_cents=None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        within = hours < 24
        print(f"Created session id={row.id} for client_id={client.id} ({phone})")
        print(f"  start={start.isoformat()}  (~{hours}h away)")
        print(f"  therapist_id={therapist.id} ({therapist.display_name})")
        print(f"  expected bot behaviour: {'BAN -> contact admin' if within else 'show reschedule/cancel options'}")
        print(f"\nTo remove later:  python scripts/seed_test_session.py --delete {row.id}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--delete":
        eng = create_engine(settings.database_url)
        with Session(eng) as db:
            row = db.get(TherapySession, int(sys.argv[2]))
            if row:
                db.delete(row)
                db.commit()
                print(f"Deleted session {sys.argv[2]}")
            else:
                print(f"No session {sys.argv[2]}")
    else:
        main()
