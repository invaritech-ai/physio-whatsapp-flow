#!/usr/bin/env bash
set -euo pipefail

# Unified local dev launcher:
# - FastAPI API server (uvicorn via uv)
# - Celery worker (via uv)
# - Celery beat scheduler (via uv)
# - Optional local Redis process

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"
API_RELOAD="${API_RELOAD:-1}"

CELERY_LOGLEVEL="${CELERY_LOGLEVEL:-info}"
CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-1}"
CELERY_BEAT_LOGLEVEL="${CELERY_BEAT_LOGLEVEL:-info}"

START_REDIS="${START_REDIS:-0}" # set to 1 to auto-start redis-server
START_BEAT="${START_BEAT:-1}"   # set to 0 to disable celery beat

PIDS=()
NAMES=()

usage() {
  cat <<'USAGE'
Usage: scripts/run_dev_stack.sh [options]

Starts API + Celery worker in one terminal.

Options:
  --with-redis        Start local redis-server in this script
  --no-beat           Disable celery beat scheduler process
  --no-reload         Disable uvicorn --reload
  --host <host>       API host (default: 0.0.0.0)
  --port <port>       API port (default: 8000)
  -h, --help          Show help

Environment overrides:
  API_HOST, API_PORT, API_RELOAD
  CELERY_LOGLEVEL, CELERY_CONCURRENCY, CELERY_BEAT_LOGLEVEL
  START_REDIS, START_BEAT
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-redis)
      START_REDIS=1
      shift
      ;;
    --no-reload)
      API_RELOAD=0
      shift
      ;;
    --no-beat)
      START_BEAT=0
      shift
      ;;
    --host)
      API_HOST="${2:-}"
      shift 2
      ;;
    --port)
      API_PORT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' not found in PATH." >&2
  exit 1
fi

if [[ "$START_REDIS" != "1" ]]; then
  if command -v redis-cli >/dev/null 2>&1; then
    if ! redis-cli ping >/dev/null 2>&1; then
      echo "Warning: redis is not reachable. Start it first, or run with --with-redis." >&2
    fi
  else
    echo "Warning: redis-cli not found; cannot verify redis availability." >&2
  fi
fi

start_bg() {
  local name="$1"
  shift
  echo "Starting ${name}: $*"
  "$@" &
  local pid=$!
  PIDS+=("$pid")
  NAMES+=("$name")
  echo "  ${name} PID=${pid}"
}

proc_name_for_pid() {
  local target_pid="$1"
  local i
  for ((i=0; i<${#PIDS[@]}; i++)); do
    if [[ "${PIDS[$i]}" == "$target_pid" ]]; then
      echo "${NAMES[$i]}"
      return 0
    fi
  done
  echo "unknown"
}

cleanup() {
  local code="${1:-0}"
  trap - INT TERM EXIT

  local pid
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done

  for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done

  exit "$code"
}

trap 'cleanup 130' INT TERM
trap 'cleanup $?' EXIT

if [[ "$START_REDIS" == "1" ]]; then
  if ! command -v redis-server >/dev/null 2>&1; then
    echo "Error: --with-redis set but redis-server not found." >&2
    exit 1
  fi
  start_bg "redis" redis-server
fi

start_bg "celery-worker" uv run celery -A app.worker:celery_app worker --loglevel="$CELERY_LOGLEVEL" --concurrency="$CELERY_CONCURRENCY"
if [[ "$START_BEAT" == "1" ]]; then
  start_bg "celery-beat" uv run celery -A app.worker:celery_app beat --loglevel="$CELERY_BEAT_LOGLEVEL"
fi

UVICORN_CMD=(uv run uvicorn app.main:app --host "$API_HOST" --port "$API_PORT")
if [[ "$API_RELOAD" == "1" ]]; then
  UVICORN_CMD+=(--reload)
fi
start_bg "api" "${UVICORN_CMD[@]}"

echo
echo "Dev stack is up. Press Ctrl+C to stop all processes."
echo

while true; do
  i=0
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      wait "$pid" || true
      name="$(proc_name_for_pid "$pid")"
      echo "Process exited: ${name} (PID=${pid}). Shutting down stack..." >&2
      cleanup 1
    fi
    i=$((i+1))
  done
  sleep 1
done
