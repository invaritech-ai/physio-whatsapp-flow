# Client Import Format (Phase 1: Clients First)

Date: 2026-02-19  
Status: Approved format draft for first migration pass

## Goal
Bulk-import clients now, even before therapist records exist, while preserving preferred therapist intent for later linking.

## Recommended Upload Strategy
Use a single CSV file with:
- required client identity fields (`phone_e164`)
- optional profile field (`name`)
- optional deferred-link fields (`preferred_therapist_email`, `preferred_therapist_display_name`)

Why this is best now:
- `Client.preferred_therapist_id` is nullable, so imports are safe without therapists.
- Email gives a stable future key because `User.email` is unique and maps to `Therapist.user_id`.
- Keeping display name as backup helps manual reconciliation if email is missing.

## CSV Columns
| Column | Required | Type | Rules | Example |
|---|---|---|---|---|
| `phone_e164` | Yes | string | Must be E.164 format: `+` followed by digits only; unique per file and DB. | `+85291234567` |
| `name` | No | string | Client display name. Empty allowed. | `John Chan` |
| `preferred_therapist_email` | No | string | Therapist staff email (future link key). Empty allowed for no preference. | `alyssa@movement.physio` |
| `preferred_therapist_display_name` | No | string | Backup reference for manual matching later. | `Dr Alyssa` |
| `notes` | No | string | Migration note only; not required by core model. | `legacy VIP client` |

## Behavioral Rules
- Upsert key: `phone_e164`.
- Initial import:
  - Create/update `Client.phone_e164`, `Client.name`.
  - Set `preferred_therapist_id = null` when therapist cannot yet be resolved.
- Deferred linking:
  - After therapist accounts exist, resolve by `preferred_therapist_email` first.
  - Use `preferred_therapist_display_name` only as manual fallback.

## Data Quality Rules
- Reject rows with invalid `phone_e164`.
- Reject duplicate `phone_e164` rows in the same file.
- Trim whitespace on all text fields.
- Treat blank therapist reference columns as "no preferred therapist".

## Two-Pass Migration Plan
1. Pass A (now): Import clients only.
2. Pass B (later): Link preferred therapists once therapists/users are seeded.

## Template File
Use: `data/templates/client_import_template.csv`

## Import Commands
Dry run (safe preview):
```bash
uv run python scripts/import_clients.py --file data/templates/client_import_template.csv
```

Apply client upsert now:
```bash
uv run python scripts/import_clients.py --file <path-to-csv> --mode upsert --apply
```

Later, link preferred therapists:
```bash
uv run python scripts/import_clients.py --file <path-to-csv> --mode link-preferred --apply \
  --unresolved-output data/imports/unresolved_preferred_therapists.csv
```
