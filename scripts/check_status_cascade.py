"""Read-only: inspect therapist/user active flags and recent status-change audit events.

Usage: uv run python scripts/check_status_cascade.py
"""

import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402


def main() -> None:
    conn_str = settings.database_url.replace("postgresql+psycopg://", "postgresql://")

    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            print("=== Therapists & linked users ===")
            cur.execute(
                'SELECT t.id, t.display_name, t.is_active, '
                "(t.calendly_user_uri IS NOT NULL) AS onboarded, "
                'u.id, u.email, u.is_active '
                'FROM therapist t JOIN "user" u ON u.id = t.user_id ORDER BY t.id'
            )
            for tid, name, t_active, onboarded, uid, email, u_active in cur.fetchall():
                print(
                    f"therapist {tid} {name!r:30s} therapist.is_active={t_active} "
                    f"onboarded={onboarded} | user {uid} {email} user.is_active={u_active}"
                )

            print("\n=== Last 5 account_status_change audit events ===")
            cur.execute(
                "SELECT id, user_id, reason, details, created_at FROM auth_event "
                "WHERE event_type = 'account_status_change' "
                "ORDER BY created_at DESC LIMIT 5"
            )
            for row in cur.fetchall():
                print(row)


if __name__ == "__main__":
    main()
