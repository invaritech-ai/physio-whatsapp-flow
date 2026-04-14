import json
from pathlib import Path
from time import time
from uuid import uuid4

DEBUG_LOG_PATH = Path("/Users/avi/.cursor/debug-logs/debug-f8a714.log")
DEBUG_SESSION_ID = "f8a714"


def debug_probe(*, run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "sessionId": DEBUG_SESSION_ID,
        "id": f"log_{int(time() * 1000)}_{uuid4().hex[:8]}",
        "timestamp": int(time() * 1000),
        "location": location,
        "message": message,
        "data": data,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
    }
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        return
