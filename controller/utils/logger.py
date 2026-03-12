"""
Centralized logging for Simulato.

All modules obtain loggers via get_logger(name).
Logs are written to both console and the system log file.
Supports deterministic replay via structured log entries.
"""

import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from controller.config import LOG_FILE, LOG_FORMAT, LOG_DATE_FORMAT, LOGS_DIR


def _ensure_log_dir() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"simulato.{name}")
    if not logger.handlers:
        _ensure_log_dir()
        logger.setLevel(logging.DEBUG)

        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


class EventLogger:
    """
    Structured event logger for replay support.

    Writes one JSON line per event to a run-specific event log.
    Each entry contains all fields required for deterministic replay
    (Canonical Law 2 + Law 11).
    """

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = run_dir
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._run_dir / "events.jsonl"
        self._logger = get_logger("event_logger")

    def log_event(self, event_type: str, data: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **data,
        }
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._logger.debug("EVENT %s: %s", event_type, json.dumps(data, ensure_ascii=False))
