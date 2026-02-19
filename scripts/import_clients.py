#!/usr/bin/env python3
"""Import clients from CSV with optional deferred therapist linking.

Usage examples:
  # Safe preview only (default: dry run)
  uv run python scripts/import_clients.py --file data/templates/client_import_template.csv

  # Apply client upserts now (no therapist linking)
  uv run python scripts/import_clients.py --file path/to/clients.csv --mode upsert --apply

  # Later, link preferred therapists after therapist accounts exist
  uv run python scripts/import_clients.py --file path/to/clients.csv --mode link-preferred --apply
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

# Add parent directory to path so we can import app modules.
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import engine
from app.models import Client, Therapist, User

PHONE_E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


@dataclass
class ImportRow:
    line_no: int
    phone_e164: str
    name: str | None
    preferred_therapist_email: str | None
    preferred_therapist_display_name: str | None
    notes: str | None


@dataclass
class ResolveResult:
    status: str  # "none" | "resolved" | "unresolved"
    therapist_id: int | None = None
    reason: str | None = None


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_phone_e164(raw_value: str | None, *, line_no: int) -> str:
    if raw_value is None:
        raise ValueError("missing required column 'phone_e164'")

    phone = raw_value.strip()
    if not phone:
        raise ValueError("phone_e164 is required")

    if phone.lower().startswith("whatsapp:"):
        phone = phone.split(":", 1)[1].strip()

    phone = (
        phone.replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    if not PHONE_E164_PATTERN.fullmatch(phone):
        raise ValueError(
            "invalid phone_e164 format; expected E.164 (e.g., +85291234567)"
        )

    return phone


def _normalize_name_key(name: str) -> str:
    return " ".join(name.strip().lower().split())


def load_rows(csv_path: Path) -> tuple[list[ImportRow], list[str]]:
    rows: list[ImportRow] = []
    errors: list[str] = []
    seen_phones: set[str] = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return [], ["CSV has no header row"]

        if "phone_e164" not in reader.fieldnames:
            return [], ["CSV is missing required column: phone_e164"]

        for line_no, raw in enumerate(reader, start=2):
            try:
                phone_e164 = _normalize_phone_e164(
                    raw.get("phone_e164"),
                    line_no=line_no,
                )
                if phone_e164 in seen_phones:
                    raise ValueError(
                        f"duplicate phone_e164 in file: {phone_e164}"
                    )
                seen_phones.add(phone_e164)

                row = ImportRow(
                    line_no=line_no,
                    phone_e164=phone_e164,
                    name=_clean_optional_text(raw.get("name")),
                    preferred_therapist_email=(
                        _clean_optional_text(raw.get("preferred_therapist_email"))
                    ),
                    preferred_therapist_display_name=(
                        _clean_optional_text(raw.get("preferred_therapist_display_name"))
                    ),
                    notes=_clean_optional_text(raw.get("notes")),
                )
                rows.append(row)
            except ValueError as exc:
                errors.append(f"line {line_no}: {exc}")

    return rows, errors


def build_therapist_lookup(
    db: Session,
) -> tuple[dict[str, int], dict[str, set[int]]]:
    email_to_therapist_id: dict[str, int] = {}
    display_name_to_therapist_ids: dict[str, set[int]] = {}

    stmt = (
        select(Therapist.id, User.email, Therapist.display_name)
        .join(User, Therapist.user_id == User.id)
    )

    for therapist_id, email, display_name in db.exec(stmt):
        if email:
            email_to_therapist_id[email.strip().lower()] = therapist_id
        if display_name:
            key = _normalize_name_key(display_name)
            display_name_to_therapist_ids.setdefault(key, set()).add(therapist_id)

    return email_to_therapist_id, display_name_to_therapist_ids


def resolve_preferred_therapist(
    row: ImportRow,
    email_lookup: dict[str, int],
    name_lookup: dict[str, set[int]],
) -> ResolveResult:
    if row.preferred_therapist_email:
        therapist_id = email_lookup.get(row.preferred_therapist_email.lower())
        if therapist_id is not None:
            return ResolveResult(status="resolved", therapist_id=therapist_id)
        return ResolveResult(status="unresolved", reason="email_not_found")

    if row.preferred_therapist_display_name:
        candidates = name_lookup.get(
            _normalize_name_key(row.preferred_therapist_display_name), set()
        )
        if len(candidates) == 1:
            return ResolveResult(
                status="resolved",
                therapist_id=next(iter(candidates)),
            )
        if len(candidates) > 1:
            return ResolveResult(
                status="unresolved",
                reason="display_name_ambiguous",
            )
        return ResolveResult(status="unresolved", reason="display_name_not_found")

    return ResolveResult(status="none")


def process_rows(
    db: Session,
    rows: list[ImportRow],
    *,
    mode: str,
    apply: bool,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    stats: dict[str, int] = {
        "total_rows": len(rows),
        "clients_created": 0,
        "clients_updated": 0,
        "clients_unchanged": 0,
        "clients_missing_for_link_mode": 0,
        "deferred_preference_rows": 0,
        "links_set": 0,
        "links_unchanged": 0,
        "links_unresolved": 0,
        "links_skipped_no_reference": 0,
    }
    unresolved: list[dict[str, Any]] = []

    needs_linking = mode in {"link-preferred", "full"}
    email_lookup: dict[str, int] = {}
    name_lookup: dict[str, set[int]] = {}
    if needs_linking:
        email_lookup, name_lookup = build_therapist_lookup(db)

    for row in rows:
        existing_client = db.exec(
            select(Client).where(Client.phone_e164 == row.phone_e164)
        ).first()

        client = existing_client

        if mode in {"upsert", "full"}:
            if existing_client is None:
                stats["clients_created"] += 1
                if apply:
                    client = Client(
                        phone_e164=row.phone_e164,
                        name=row.name,
                        conversation_state="IDLE",
                    )
                    db.add(client)
            else:
                name_changed = bool(row.name and row.name != existing_client.name)
                if name_changed:
                    stats["clients_updated"] += 1
                    if apply:
                        existing_client.name = row.name
                        db.add(existing_client)
                else:
                    stats["clients_unchanged"] += 1

            if row.preferred_therapist_email or row.preferred_therapist_display_name:
                if mode == "upsert":
                    stats["deferred_preference_rows"] += 1

        if mode == "link-preferred" and existing_client is None:
            stats["clients_missing_for_link_mode"] += 1
            if row.preferred_therapist_email or row.preferred_therapist_display_name:
                unresolved.append(
                    {
                        "line_no": row.line_no,
                        "phone_e164": row.phone_e164,
                        "preferred_therapist_email": row.preferred_therapist_email or "",
                        "preferred_therapist_display_name": row.preferred_therapist_display_name or "",
                        "reason": "client_not_found",
                    }
                )
            continue

        if not needs_linking:
            continue

        resolution = resolve_preferred_therapist(row, email_lookup, name_lookup)
        if resolution.status == "none":
            stats["links_skipped_no_reference"] += 1
            continue

        if resolution.status == "unresolved":
            stats["links_unresolved"] += 1
            unresolved.append(
                {
                    "line_no": row.line_no,
                    "phone_e164": row.phone_e164,
                    "preferred_therapist_email": row.preferred_therapist_email or "",
                    "preferred_therapist_display_name": row.preferred_therapist_display_name or "",
                    "reason": resolution.reason or "unknown",
                }
            )
            continue

        assert resolution.therapist_id is not None
        current_preferred = existing_client.preferred_therapist_id if existing_client else None
        if current_preferred == resolution.therapist_id:
            stats["links_unchanged"] += 1
            continue

        stats["links_set"] += 1

        if apply:
            if client is None:
                # This only occurs for dry-run created rows; apply mode should always
                # have a client object by here.
                raise RuntimeError("internal error: missing client object during linking")
            client.preferred_therapist_id = resolution.therapist_id
            db.add(client)

    return stats, unresolved


def write_unresolved_report(path: Path, unresolved: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "line_no",
                "phone_e164",
                "preferred_therapist_email",
                "preferred_therapist_display_name",
                "reason",
            ],
        )
        writer.writeheader()
        writer.writerows(unresolved)


def print_summary(
    stats: dict[str, int],
    *,
    mode: str,
    apply: bool,
    validation_errors: list[str],
    unresolved: list[dict[str, Any]],
    unresolved_output: Path | None,
) -> None:
    print("\n" + "=" * 60)
    print("CLIENT IMPORT SUMMARY")
    print("=" * 60)
    print(f"Mode:        {mode}")
    print(f"Apply:       {apply}")
    print(f"Total rows:  {stats['total_rows']}")
    print(f"Bad rows:    {len(validation_errors)}")

    print("\nUpsert stats:")
    print(f"  Created:   {stats['clients_created']}")
    print(f"  Updated:   {stats['clients_updated']}")
    print(f"  Unchanged: {stats['clients_unchanged']}")
    print(f"  Deferred preference rows: {stats['deferred_preference_rows']}")
    print(f"  Missing clients (link mode only): {stats['clients_missing_for_link_mode']}")

    print("\nLink stats:")
    print(f"  Links set:       {stats['links_set']}")
    print(f"  Links unchanged: {stats['links_unchanged']}")
    print(f"  Unresolved refs: {stats['links_unresolved']}")
    print(f"  No reference:    {stats['links_skipped_no_reference']}")

    if validation_errors:
        print("\nValidation errors:")
        for err in validation_errors[:20]:
            print(f"  - {err}")
        if len(validation_errors) > 20:
            print(f"  ... and {len(validation_errors) - 20} more")

    if unresolved:
        print("\nUnresolved therapist references (first 20):")
        for item in unresolved[:20]:
            print(
                "  - line {line_no}: {phone_e164} ({reason}) email='{preferred_therapist_email}' name='{preferred_therapist_display_name}'".format(
                    **item
                )
            )
        if len(unresolved) > 20:
            print(f"  ... and {len(unresolved) - 20} more")
        if unresolved_output:
            print(f"\nUnresolved report: {unresolved_output}")

    if not apply:
        print("\nDry run only: no database changes were committed.")

    print("=" * 60 + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import clients from CSV.")
    parser.add_argument(
        "--file",
        required=True,
        help="Path to CSV file containing client rows.",
    )
    parser.add_argument(
        "--mode",
        choices=["upsert", "link-preferred", "full"],
        default="upsert",
        help=(
            "upsert: create/update clients only; "
            "link-preferred: set preferred_therapist_id on existing clients only; "
            "full: upsert clients and attempt preferred therapist linking."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit database changes. Omit for dry run.",
    )
    parser.add_argument(
        "--unresolved-output",
        help="Optional CSV path to write unresolved therapist references.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    csv_path = Path(args.file)
    unresolved_output = (
        Path(args.unresolved_output) if args.unresolved_output else None
    )

    if not csv_path.exists():
        print(f"ERROR: file not found: {csv_path}")
        return 1

    rows, validation_errors = load_rows(csv_path)
    if validation_errors:
        print("Input validation failed. Fix errors and retry.")
        for err in validation_errors[:20]:
            print(f"  - {err}")
        if len(validation_errors) > 20:
            print(f"  ... and {len(validation_errors) - 20} more")
        return 1

    try:
        with Session(engine) as db:
            stats, unresolved = process_rows(
                db,
                rows,
                mode=args.mode,
                apply=args.apply,
            )

            if unresolved_output:
                write_unresolved_report(unresolved_output, unresolved)

            if args.apply:
                db.commit()
            else:
                db.rollback()

            print_summary(
                stats,
                mode=args.mode,
                apply=args.apply,
                validation_errors=validation_errors,
                unresolved=unresolved,
                unresolved_output=unresolved_output,
            )

    except SQLAlchemyError as exc:
        print(f"Database error: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
