from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


_LOG_PATH = (Path(__file__).resolve().parents[2] / "debug-5f7685.log")
_SESSION_ID = "5f7685"


def dbg(
    *,
    location: str,
    message: str,
    data: Optional[dict[str, Any]] = None,
    hypothesisId: str = "H0",
    runId: str = "pre-fix",
) -> None:
    """
    Debug-mode NDJSON logger.
    Writes one JSON object per line to debug-5f7685.log.
    Do not log secrets (API keys, tokens, PII).
    """
    payload: dict[str, Any] = {
        "sessionId": _SESSION_ID,
        "hypothesisId": hypothesisId,
        "runId": runId,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Never break runtime due to debug logging.
        pass

