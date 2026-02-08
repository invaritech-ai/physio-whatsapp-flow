#!/usr/bin/env python3
"""Check the results of the bot flow test."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select

from app.db.session import engine
from app.models import Client, MessageLog, Therapist

def main():
    phone = "+85299887766"

    with Session(engine) as db:
        # Get client
        client = db.exec(select(Client).where(Client.phone_e164 == phone)).first()

        if not client:
            print(f"❌ No client found with phone {phone}")
            print("   Bot flow may have failed. Check Celery worker logs.")
            return

        print("=" * 60)
        print("CLIENT RECORD")
        print("=" * 60)
        print(f"ID: {client.id}")
        print(f"Phone: {client.phone_e164}")
        print(f"Name: {client.name}")
        print(f"Conversation State: {client.conversation_state}")
        print(f"Preferred Therapist ID: {client.preferred_therapist_id}")
        print(f"Conversation Data: {json.dumps(client.conversation_data, indent=2)}")

        # Get preferred therapist if set
        if client.preferred_therapist_id:
            therapist = db.get(Therapist, client.preferred_therapist_id)
            if therapist:
                print(f"\n✓ Matched Therapist: {therapist.display_name}")
                print(f"  Calendly URI: {therapist.calendly_user_uri}")

        # Get message logs
        logs = db.exec(
            select(MessageLog)
            .where(MessageLog.client_id == client.id)
            .order_by(MessageLog.created_at)
        ).all()

        print("\n" + "=" * 60)
        print(f"MESSAGE LOGS ({len(logs)} messages)")
        print("=" * 60)

        for i, log in enumerate(logs, 1):
            direction_icon = "→" if log.direction == "outbound" else "←"
            print(f"{i}. {direction_icon} {log.direction.upper()}: {log.body[:80]}")
            if len(log.body) > 80:
                print(f"   (... {len(log.body) - 80} more chars)")

        # Final assessment
        print("\n" + "=" * 60)
        print("FLOW ASSESSMENT")
        print("=" * 60)

        if client.conversation_state == "IDLE":
            print("✓ Flow completed successfully (state = IDLE)")
        else:
            print(f"⚠ Flow incomplete (state = {client.conversation_state})")

        if client.preferred_therapist_id:
            print(f"✓ Client matched to therapist ID {client.preferred_therapist_id}")
        else:
            print("⚠ No therapist matched yet")

        if client.conversation_data:
            print(f"✓ Conversation data captured:")
            # Parse JSON string if needed
            if isinstance(client.conversation_data, str):
                data = json.loads(client.conversation_data)
            else:
                data = client.conversation_data
            for key, value in data.items():
                print(f"  - {key}: {value}")
        else:
            print("⚠ No conversation data saved")

        expected_logs = 14  # 7 inbound + 7 outbound
        if len(logs) >= expected_logs:
            print(f"✓ All messages logged ({len(logs)} >= {expected_logs} expected)")
        else:
            print(f"⚠ Missing message logs ({len(logs)} < {expected_logs} expected)")

        print("=" * 60)


if __name__ == "__main__":
    main()
