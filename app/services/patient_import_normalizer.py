from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

PHONE_E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")

NORMALIZED_FIELDNAMES = [
    "id",
    "phone_e164",
    "name",
    "email",
    "date_of_birth",
    "address",
    "conversation_state",
    "preferred_therapist_id",
    "default_receipt_amount_cents",
]

SKIPPED_FIELDNAMES = [
    "patient_number",
    "patient_guid",
    "name",
    "chosen_phone",
    "skip_reason",
]

CANONICAL_PATIENT_BY_PHONE = {
    "+85263121852": "7",
    "+85295480821": "19",
}

EXCLUDED_DUPLICATE_PATIENT_NUMBERS = {"2", "30"}


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def _combine_name(row: dict[str, str]) -> str:
    return " ".join(part for part in [_clean(row.get("First Name")), _clean(row.get("Last Name"))] if part)


def _choose_phone(row: dict[str, str]) -> str:
    return (
        _clean(row.get("Mobile Phone"))
        or _clean(row.get("Home Phone"))
        or _clean(row.get("Work Phone"))
    )


def _combine_address(row: dict[str, str]) -> str:
    parts = [
        _clean(row.get("Street Address")),
        _clean(row.get("Street Address 2")),
        _clean(row.get("City")),
        _clean(row.get("Province")),
        _clean(row.get("Postal")),
        _clean(row.get("Country")),
    ]
    return ", ".join(part for part in parts if part)


def normalize_patient_rows(
    raw_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows_by_phone: dict[str, list[dict[str, str]]] = defaultdict(list)
    normalized_rows: list[dict[str, str]] = []
    skipped_rows: list[dict[str, str]] = []

    for row in raw_rows:
        phone = _choose_phone(row)
        if phone:
            rows_by_phone[phone].append(row)

    duplicate_phones = {phone for phone, rows in rows_by_phone.items() if len(rows) > 1}

    for row in raw_rows:
        patient_number = _clean(row.get("Patient Number"))
        patient_guid = _clean(row.get("patient_guid"))
        name = _combine_name(row)
        phone = _choose_phone(row)

        if not phone:
            skipped_rows.append(
                {
                    "patient_number": patient_number,
                    "patient_guid": patient_guid,
                    "name": name,
                    "chosen_phone": "",
                    "skip_reason": "missing_phone",
                }
            )
            continue

        if not PHONE_E164_PATTERN.fullmatch(phone):
            skipped_rows.append(
                {
                    "patient_number": patient_number,
                    "patient_guid": patient_guid,
                    "name": name,
                    "chosen_phone": phone,
                    "skip_reason": "invalid_phone",
                }
            )
            continue

        if phone in duplicate_phones:
            if patient_number in EXCLUDED_DUPLICATE_PATIENT_NUMBERS:
                skipped_rows.append(
                    {
                        "patient_number": patient_number,
                        "patient_guid": patient_guid,
                        "name": name,
                        "chosen_phone": phone,
                        "skip_reason": "duplicate_phone_excluded_cluster",
                    }
                )
                continue

            canonical_patient_number = CANONICAL_PATIENT_BY_PHONE.get(phone)
            if canonical_patient_number is None:
                skipped_rows.append(
                    {
                        "patient_number": patient_number,
                        "patient_guid": patient_guid,
                        "name": name,
                        "chosen_phone": phone,
                        "skip_reason": "duplicate_phone_unresolved",
                    }
                )
                continue

            if patient_number != canonical_patient_number:
                skip_reason = (
                    "duplicate_phone_excluded_cluster"
                    if patient_number in EXCLUDED_DUPLICATE_PATIENT_NUMBERS
                    else "duplicate_phone_non_canonical"
                )
                skipped_rows.append(
                    {
                        "patient_number": patient_number,
                        "patient_guid": patient_guid,
                        "name": name,
                        "chosen_phone": phone,
                        "skip_reason": skip_reason,
                    }
                )
                continue

        normalized_rows.append(
            {
                "id": patient_number,
                "phone_e164": phone,
                "name": name,
                "email": _clean(row.get("Email")),
                "date_of_birth": _clean(row.get("Birth Date")),
                "address": _combine_address(row),
                "conversation_state": "IDLE",
                "preferred_therapist_id": "",
                "default_receipt_amount_cents": "",
            }
        )

    return normalized_rows, skipped_rows


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def write_rows(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
