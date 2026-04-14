"""Structured process tracing when DEBUG_MODE=true.

Emit grep-friendly JSON lines: [PROCESS-TRACE] {"trace_id", "channel", "stage", ...}
Use for webhooks and synchronous business logic; gate with settings.debug_mode to avoid prod noise.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger("app.process_trace")
_process_start = perf_counter()

_trace_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "process_trace_id", default=None
)

CHANNEL_CALENDLY_WEBHOOK = "calendly_webhook"
CHANNEL_WHATSAPP_WEBHOOK = "whatsapp_webhook"
CHANNEL_WHATSAPP_BOT = "whatsapp_bot"


def get_trace_id() -> str | None:
    return _trace_id_ctx.get()


def set_trace_id(value: str | None) -> contextvars.Token:
    return _trace_id_ctx.set(value)


def reset_trace_id(token: contextvars.Token) -> None:
    _trace_id_ctx.reset(token)


def new_trace_id() -> tuple[str, contextvars.Token]:
    tid = str(uuid4())
    token = set_trace_id(tid)
    return tid, token


def process_trace(channel: str, stage: str, **fields: Any) -> None:
    if not settings.debug_mode:
        return
    row: dict[str, Any] = {
        "trace_id": get_trace_id(),
        "channel": channel,
        "stage": stage,
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
        "server_uptime_ms": round((perf_counter() - _process_start) * 1000, 2),
        **fields,
    }
    try:
        line = json.dumps(row, default=str)
    except Exception:
        line = str(row)
    logger.info("[PROCESS-TRACE] %s", line)


def attach_trace_to_result(result: dict[str, Any]) -> dict[str, Any]:
    if not settings.debug_mode:
        return result
    tid = get_trace_id()
    if tid:
        return {**result, "trace_id": tid}
    return result


def mask_twilio_whatsapp_from(value: str | None) -> str:
    """Mask E.164 tail after whatsapp: prefix."""
    if not value:
        return ""
    text = value.strip()
    m = re.search(r"(\+\d{4,})(?:\s|$)", text)
    if m:
        tail = m.group(1)
        return f"whatsapp:***{tail[-4:]}"
    return "***"
