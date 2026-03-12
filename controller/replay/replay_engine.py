"""
Replay engine — deterministic decision re-execution.

Reads stored artifacts from a completed run and re-executes
the decision pipeline offline, comparing results to verify
that the system produces identical decisions given identical inputs.

Required artifacts per question (stored by WorkflowEngine):
    - screenshots (JPEG)
    - AI response JSON
    - event log (JSONL)
    - database state at time of run

Replay flow:
    1. Load event log for the run
    2. For each question event:
       a. Load the stored AI response JSON
       b. Re-run the decision engine against the database
       c. Compare replay decision to original decision
       d. Record match / mismatch
    3. Produce a ReplayReport

(Canonical Law 2 — Deterministic Execution, Law 11 — Full Replay Support)
"""

import json
from pathlib import Path
from typing import Optional

from controller.ai_pipeline.response_parser import GrokResponse
from controller.answer_engine.decision_engine import (
    decide_answer,
    AnswerDecision,
    DecisionOutcome,
)
from controller.utils.logger import get_logger
from database.db_manager import DatabaseManager

logger = get_logger("replay_engine")


class ReplayQuestionResult:
    """Result of replaying a single question decision."""

    def __init__(
        self,
        question_number: int,
        original_letter: Optional[str],
        original_source: Optional[str],
        replay_letter: Optional[str],
        replay_source: Optional[str],
        match: bool,
        details: str = "",
    ) -> None:
        self.question_number = question_number
        self.original_letter = original_letter
        self.original_source = original_source
        self.replay_letter = replay_letter
        self.replay_source = replay_source
        self.match = match
        self.details = details


class ReplayReport:
    """Summary report for a full replay session."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.results: list[ReplayQuestionResult] = []
        self.total_questions = 0
        self.matches = 0
        self.mismatches = 0
        self.errors = 0

    @property
    def all_match(self) -> bool:
        return self.mismatches == 0 and self.errors == 0

    def add_result(self, result: ReplayQuestionResult) -> None:
        self.results.append(result)
        self.total_questions += 1
        if result.match:
            self.matches += 1
        elif result.details.startswith("error"):
            self.errors += 1
        else:
            self.mismatches += 1

    def summary(self) -> str:
        status = "PASS" if self.all_match else "FAIL"
        return (
            f"Replay Report [{status}] run={self.run_id}: "
            f"total={self.total_questions}, matches={self.matches}, "
            f"mismatches={self.mismatches}, errors={self.errors}"
        )


class ReplayEngine:
    """
    Re-executes the decision pipeline against stored artifacts
    and verifies deterministic behavior.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def replay_run(self, run_dir: Path) -> ReplayReport:
        """
        Replay all decisions from a completed run.

        Args:
            run_dir: Path to the run directory containing
                     events.jsonl and ai_responses/.

        Returns:
            ReplayReport with per-question comparison results.
        """
        run_id = run_dir.name
        report = ReplayReport(run_id)
        logger.info("Starting replay for run: %s", run_id)

        event_log_path = run_dir / "events.jsonl"
        if not event_log_path.exists():
            logger.error("Event log not found: %s", event_log_path)
            return report

        ai_responses_dir = run_dir / "ai_responses"
        if not ai_responses_dir.exists():
            logger.error("AI responses directory not found: %s", ai_responses_dir)
            return report

        events = self._load_events(event_log_path)
        decision_events = [
            e for e in events if e.get("event_type") == "answer_decision"
        ]

        logger.info(
            "Found %d answer_decision events in %d total events",
            len(decision_events), len(events),
        )

        for event in decision_events:
            qnum = event.get("question_number")
            original_letter = event.get("click_letter")
            original_source = event.get("source")
            test_name = event.get("test_name")

            result = self._replay_single_question(
                run_dir=run_dir,
                question_number=qnum,
                original_letter=original_letter,
                original_source=original_source,
                test_name=test_name,
            )
            report.add_result(result)

        logger.info(report.summary())
        return report

    def _replay_single_question(
        self,
        run_dir: Path,
        question_number: int,
        original_letter: Optional[str],
        original_source: Optional[str],
        test_name: Optional[str],
    ) -> ReplayQuestionResult:
        """Replay a single question decision and compare."""
        ai_response_path = run_dir / "ai_responses" / f"ai_response_{question_number:04d}.json"

        if not ai_response_path.exists():
            logger.warning("AI response file missing for Q%d: %s", question_number, ai_response_path)
            return ReplayQuestionResult(
                question_number=question_number,
                original_letter=original_letter,
                original_source=original_source,
                replay_letter=None,
                replay_source=None,
                match=False,
                details="error_missing_ai_response",
            )

        try:
            ai_data = json.loads(ai_response_path.read_text(encoding="utf-8"))
            grok_response = GrokResponse(**ai_data)
        except Exception as e:
            logger.error("Failed to parse AI response for Q%d: %s", question_number, e)
            return ReplayQuestionResult(
                question_number=question_number,
                original_letter=original_letter,
                original_source=original_source,
                replay_letter=None,
                replay_source=None,
                match=False,
                details=f"error_parse: {e}",
            )

        test_name = test_name or "unknown"
        test = self._db.get_test_by_name(test_name)
        if test is None:
            logger.error("Test '%s' not found in database", test_name)
            return ReplayQuestionResult(
                question_number=question_number,
                original_letter=original_letter,
                original_source=original_source,
                replay_letter=None,
                replay_source=None,
                match=False,
                details=f"error_test_not_found: {test_name}",
            )

        try:
            replay_decision = decide_answer(self._db, test["test_id"], grok_response)
        except Exception as e:
            logger.error("Decision engine failed during replay for Q%d: %s", question_number, e)
            return ReplayQuestionResult(
                question_number=question_number,
                original_letter=original_letter,
                original_source=original_source,
                replay_letter=None,
                replay_source=None,
                match=False,
                details=f"error_decision: {e}",
            )

        replay_letter = replay_decision.click_letter
        replay_source = replay_decision.source

        match = (
            replay_letter == original_letter
            and replay_decision.outcome != DecisionOutcome.ERROR
        )

        if match:
            logger.info(
                "Q%d MATCH: letter=%s, source=%s→%s",
                question_number, original_letter, original_source, replay_source,
            )
        else:
            logger.warning(
                "Q%d MISMATCH: original=%s(%s), replay=%s(%s)",
                question_number,
                original_letter, original_source,
                replay_letter, replay_source,
            )

        return ReplayQuestionResult(
            question_number=question_number,
            original_letter=original_letter,
            original_source=original_source,
            replay_letter=replay_letter,
            replay_source=replay_source,
            match=match,
            details="" if match else f"letter_diff: {original_letter} vs {replay_letter}",
        )

    def _load_events(self, path: Path) -> list[dict]:
        """Load all events from a JSONL file."""
        events = []
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning("Malformed event at line %d: %s", line_num, e)
        return events
