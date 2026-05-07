#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.patient_import_normalizer import (
    NORMALIZED_FIELDNAMES,
    SKIPPED_FIELDNAMES,
    normalize_patient_rows,
    read_rows,
    write_rows,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize the Movement Group patient export into import-safe CSV files."
    )
    parser.add_argument("--source", type=Path, required=True, help="Source patient export CSV")
    parser.add_argument(
        "--normalized-output",
        type=Path,
        default=Path("data/imports/movement_group_patients_normalized_20260430.csv"),
        help="Output CSV containing import-safe client rows",
    )
    parser.add_argument(
        "--skipped-output",
        type=Path,
        default=Path("data/imports/movement_group_patients_skipped_20260430.csv"),
        help="Output CSV containing skipped source rows with reasons",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    raw_rows = read_rows(args.source)
    normalized_rows, skipped_rows = normalize_patient_rows(raw_rows)

    write_rows(args.normalized_output, NORMALIZED_FIELDNAMES, normalized_rows)
    write_rows(args.skipped_output, SKIPPED_FIELDNAMES, skipped_rows)

    print(f"source_rows={len(raw_rows)}")
    print(f"normalized_rows={len(normalized_rows)}")
    print(f"skipped_rows={len(skipped_rows)}")
    print(f"normalized_output={args.normalized_output}")
    print(f"skipped_output={args.skipped_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
