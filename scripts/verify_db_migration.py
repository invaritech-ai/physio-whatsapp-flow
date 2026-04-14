#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

import psycopg
from psycopg import sql

DEFAULT_TABLES = [
    "client",
    "message_log",
    "therapist",
    "session",
    "payment_record",
    "payment_proof",
    "booking_intent",
    "session_note",
    "alembic_version",
]


@dataclass
class TableCheck:
    table: str
    old_count: int | None
    new_count: int | None

    @property
    def matches(self) -> bool:
        return self.old_count is not None and self.old_count == self.new_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify full-clone migration by comparing row counts and alembic revision."
    )
    parser.add_argument("--old-db-url", default=os.getenv("OLD_DATABASE_URL"))
    parser.add_argument("--new-db-url", default=os.getenv("NEW_DATABASE_URL"))
    parser.add_argument(
        "--tables",
        default=",".join(DEFAULT_TABLES),
        help="Comma-separated table list to compare (default: critical tables).",
    )
    parser.add_argument(
        "--allow-count-drift",
        type=int,
        default=0,
        help="Allowed absolute row-count difference per table (default: 0).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output for automation.",
    )
    return parser.parse_args()


def fetch_row_count(conn: psycopg.Connection, table_name: str) -> int | None:
    with conn.cursor() as cur:
        try:
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name)))
        except psycopg.errors.UndefinedTable:
            conn.rollback()
            return None
        return int(cur.fetchone()[0])


def fetch_alembic_version(conn: psycopg.Connection) -> str | None:
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
        except Exception:
            return None
        row = cur.fetchone()
        return row[0] if row else None


def main() -> int:
    args = parse_args()
    if not args.old_db_url or not args.new_db_url:
        print("Both --old-db-url and --new-db-url (or env vars) are required.", file=sys.stderr)
        return 2

    tables = [part.strip() for part in args.tables.split(",") if part.strip()]
    if not tables:
        print("No tables provided for verification.", file=sys.stderr)
        return 2

    checks: list[TableCheck] = []
    mismatches: list[str] = []

    with psycopg.connect(args.old_db_url) as old_conn, psycopg.connect(args.new_db_url) as new_conn:
        for table_name in tables:
            old_count = fetch_row_count(old_conn, table_name)
            new_count = fetch_row_count(new_conn, table_name)
            checks.append(TableCheck(table=table_name, old_count=old_count, new_count=new_count))
            if old_count is None or new_count is None:
                mismatches.append(table_name)
                continue
            if abs(old_count - new_count) > args.allow_count_drift:
                mismatches.append(table_name)

        old_revision = fetch_alembic_version(old_conn)
        new_revision = fetch_alembic_version(new_conn)
        revision_match = old_revision == new_revision and old_revision is not None

    output = {
        "tables": [
            {
                "table": c.table,
                "old_count": c.old_count,
                "new_count": c.new_count,
                "matches": c.matches,
            }
            for c in checks
        ],
        "alembic": {
            "old_revision": old_revision,
            "new_revision": new_revision,
            "matches": revision_match,
        },
        "allow_count_drift": args.allow_count_drift,
        "count_mismatch_tables": mismatches,
        "ok": not mismatches and revision_match,
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print("Table row-count comparison:")
        for check in checks:
            marker = "OK" if check.matches else "MISMATCH"
            print(f"- {check.table}: old={check.old_count}, new={check.new_count} [{marker}]")
        print(
            f"Alembic revision: old={old_revision!r}, new={new_revision!r}, "
            f"match={'YES' if revision_match else 'NO'}"
        )
        print(f"Overall verification: {'PASS' if output['ok'] else 'FAIL'}")

    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
