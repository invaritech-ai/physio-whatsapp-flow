#!/usr/bin/env bash

set -euo pipefail

MODE="full"
BACKUP_FILE="${BACKUP_FILE:-}"

usage() {
  cat <<'EOF'
Usage:
  OLD_DATABASE_URL=... NEW_DATABASE_URL=... ./scripts/migrate_db_full_clone.sh [--full|--dump-only|--restore-only] [--backup-file PATH]

Modes:
  --full          Dump OLD_DATABASE_URL then restore into NEW_DATABASE_URL (default)
  --dump-only     Only run pg_dump from OLD_DATABASE_URL
  --restore-only  Only run pg_restore into NEW_DATABASE_URL using --backup-file (or BACKUP_FILE)

Environment:
  OLD_DATABASE_URL   Source PostgreSQL URL (required for --full/--dump-only)
  NEW_DATABASE_URL   Target PostgreSQL URL (required for --full/--restore-only)
  BACKUP_FILE        Optional path for dump file (default: ./db-backup-YYYYmmdd-HHMMSS.dump)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full)
      MODE="full"
      shift
      ;;
    --dump-only)
      MODE="dump-only"
      shift
      ;;
    --restore-only)
      MODE="restore-only"
      shift
      ;;
    --backup-file)
      BACKUP_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: $name" >&2
    exit 1
  fi
}

timestamp() {
  date +"%Y%m%d-%H%M%S"
}

log() {
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $*"
}

if [[ -z "${BACKUP_FILE}" ]]; then
  BACKUP_FILE="./db-backup-$(timestamp).dump"
fi

require_cmd pg_dump
require_cmd pg_restore

run_dump() {
  require_env OLD_DATABASE_URL
  log "Starting pg_dump to ${BACKUP_FILE}"
  pg_dump "${OLD_DATABASE_URL}" \
    --format=custom \
    --no-owner \
    --no-acl \
    --file "${BACKUP_FILE}"
  log "Dump completed: ${BACKUP_FILE}"
}

run_restore() {
  require_env NEW_DATABASE_URL
  if [[ ! -f "${BACKUP_FILE}" ]]; then
    echo "Backup file not found: ${BACKUP_FILE}" >&2
    exit 1
  fi
  log "Starting pg_restore from ${BACKUP_FILE}"
  pg_restore \
    --clean \
    --if-exists \
    --no-owner \
    --no-acl \
    --exit-on-error \
    --dbname="${NEW_DATABASE_URL}" \
    "${BACKUP_FILE}"
  log "Restore completed into target database"
}

case "${MODE}" in
  full)
    require_env OLD_DATABASE_URL
    require_env NEW_DATABASE_URL
    run_dump
    run_restore
    ;;
  dump-only)
    run_dump
    ;;
  restore-only)
    run_restore
    ;;
  *)
    echo "Unsupported mode: ${MODE}" >&2
    exit 1
    ;;
esac

log "Migration script finished successfully (mode=${MODE})"
