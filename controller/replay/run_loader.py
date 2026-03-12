"""
Run loader — discovers and validates completed run directories.

Each run directory contains:
    - events.jsonl (event log)
    - ai_responses/ (per-question AI response JSON)
    - screenshots/ (captured images)

This module provides utilities to list available runs,
validate their completeness, and load metadata.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from controller.config import RUNS_DIR
from controller.utils.logger import get_logger

logger = get_logger("run_loader")


class RunContext:
    """Context for an active run — created by create_run()."""

    def __init__(self, run_id: str, run_dir: Path) -> None:
        self.run_id = run_id
        self.run_dir = run_dir


def create_run(test_name: str, runs_dir: Optional[Path] = None) -> RunContext:
    """
    Create a new timestamped run directory with artifact subdirs.

    Args:
        test_name: Base name for the run.
        runs_dir: Optional override for runs directory.

    Returns:
        RunContext with run_id and run_dir.
    """
    base = runs_dir or RUNS_DIR
    base.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"{test_name}_{timestamp}" if test_name else timestamp
    run_dir = base / run_id

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "screenshots").mkdir(exist_ok=True)
    (run_dir / "ai_responses").mkdir(exist_ok=True)

    logger.info("Created run: %s at %s", run_id, run_dir)
    return RunContext(run_id=run_id, run_dir=run_dir)


class RunMetadata:
    """Metadata for a completed run."""

    def __init__(
        self,
        run_id: str,
        run_dir: Path,
        event_count: int,
        ai_response_count: int,
        screenshot_count: int,
        is_complete: bool,
    ) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.event_count = event_count
        self.ai_response_count = ai_response_count
        self.screenshot_count = screenshot_count
        self.is_complete = is_complete


def list_runs(runs_dir: Optional[Path] = None) -> list[RunMetadata]:
    """
    List all available run directories with metadata.

    Returns list sorted by run_id (most recent first).
    """
    base = runs_dir or RUNS_DIR
    if not base.exists():
        logger.info("No runs directory at %s", base)
        return []

    runs = []
    for entry in sorted(base.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name == "replay_sessions":
            continue

        meta = _inspect_run(entry)
        if meta is not None:
            runs.append(meta)

    logger.info("Found %d runs in %s", len(runs), base)
    return runs


def load_run(run_id: str, runs_dir: Optional[Path] = None) -> Optional[RunMetadata]:
    """Load metadata for a specific run by ID."""
    base = runs_dir or RUNS_DIR
    run_dir = base / run_id
    if not run_dir.exists():
        logger.warning("Run not found: %s", run_id)
        return None
    return _inspect_run(run_dir)


def _inspect_run(run_dir: Path) -> Optional[RunMetadata]:
    """Inspect a run directory and extract metadata."""
    events_path = run_dir / "events.jsonl"
    ai_dir = run_dir / "ai_responses"
    screenshots_dir = run_dir / "screenshots"

    event_count = 0
    if events_path.exists():
        with open(events_path, "r", encoding="utf-8") as f:
            event_count = sum(1 for line in f if line.strip())

    ai_count = len(list(ai_dir.glob("*.json"))) if ai_dir.exists() else 0
    ss_count = len(list(screenshots_dir.glob("*.jpg"))) + len(list(screenshots_dir.glob("*.png"))) if screenshots_dir.exists() else 0

    is_complete = events_path.exists() and ai_count > 0

    return RunMetadata(
        run_id=run_dir.name,
        run_dir=run_dir,
        event_count=event_count,
        ai_response_count=ai_count,
        screenshot_count=ss_count,
        is_complete=is_complete,
    )
