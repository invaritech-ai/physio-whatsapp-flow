#!/usr/bin/env python3
"""Clean up test client data to reset for a fresh test."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select

from app.db.session import engine
from app.models import Client, MessageLog


def main():
    phone = "+85299887766"

    with Session(engine) as db:
        # Get client
        client = db.exec(select(Client).where(Client.phone_e164 == phone)).first()

        if not client:
            print(f"No client found with phone {phone}")
            return

        # Delete message logs
        logs = db.exec(
            select(MessageLog).where(MessageLog.client_id == client.id)
        ).all()

        for log in logs:
            db.delete(log)

        # Delete client
        db.delete(client)
        db.commit()

        print(f"✓ Deleted client {phone} and {len(logs)} message logs")
        print("  Ready for a fresh test!")


if __name__ == "__main__":
    main()
