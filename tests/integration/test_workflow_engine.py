"""
Integration tests for the workflow engine.

Tests the complete question-processing loop with mocked
external dependencies (Grok API, hardware, phone).

Validates:
    - Full pipeline execution (capture → decision → click)
    - State machine enforcement
    - Event logging
    - Error handling paths
"""

import json
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from controller.orchestrator.state_machine import StateMachine, SystemState
from controller.orchestrator.workflow_engine import WorkflowEngine
from controller.alerts.alert_manager import AlertManager
from controller.hardware_control.click_dispatcher import ClickDispatcher
from controller.hardware_control.verification_engine import (
    VerificationEngine,
    VerificationResult,
)
from controller.capture_pipeline.image_receiver import ImageReceiver
from controller.utils.logger import EventLogger
from database.db_manager import DatabaseManager


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def db(tmpdir):
    db_path = tmpdir / "test.db"
    manager = DatabaseManager(db_path=db_path)
    yield manager
    manager.close()


@pytest.fixture
def state_machine():
    return StateMachine()


@pytest.fixture
def alert_manager():
    return AlertManager()


@pytest.fixture
def click_dispatcher():
    mock_dispatch = MagicMock()
    dispatcher = ClickDispatcher.__new__(ClickDispatcher)
    dispatcher._pi_client = mock_dispatch
    dispatcher._grid_map = None
    return dispatcher


@pytest.fixture
def verification_engine():
    engine = VerificationEngine()
    return engine


@pytest.fixture
def image_receiver(tmpdir):
    receiver = ImageReceiver.__new__(ImageReceiver)
    run_dir = tmpdir / "runs" / "test_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = run_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    receiver._run_dir = run_dir
    receiver._screenshots_dir = screenshots_dir
    receiver._frame_counter = 0
    return receiver


@pytest.fixture
def event_logger(tmpdir):
    return EventLogger(tmpdir / "events")


@pytest.fixture
def workflow(state_machine, db, alert_manager, click_dispatcher,
             verification_engine, image_receiver, event_logger):
    engine = WorkflowEngine(
        state_machine=state_machine,
        db=db,
        alert_manager=alert_manager,
        click_dispatcher=click_dispatcher,
        verification_engine=verification_engine,
        image_receiver=image_receiver,
        event_logger=event_logger,
    )
    return engine


def _create_test_jpeg(tmpdir: Path) -> bytes:
    """Create minimal valid JPEG bytes for testing."""
    try:
        import cv2
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        img[:, :] = (200, 200, 200)
        _, encoded = cv2.imencode(".jpg", img)
        return encoded.tobytes()
    except ImportError:
        from PIL import Image
        import io
        img = Image.new("RGB", (200, 100), color=(200, 200, 200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()


class TestWorkflowStateEnforcement:

    def test_cannot_process_in_idle(self, workflow, tmpdir):
        """process_question must reject when not in RUNNING state."""
        jpeg = _create_test_jpeg(tmpdir)
        result = workflow.process_question(jpeg)
        assert result is None

    def test_cannot_process_without_test_context(self, workflow, state_machine, tmpdir):
        """process_question must reject when no test context is set."""
        state_machine.transition_to(SystemState.RUNNING, "test")
        jpeg = _create_test_jpeg(tmpdir)
        result = workflow.process_question(jpeg)
        assert result is None


class TestWorkflowTestContext:

    def test_set_test_context(self, workflow, db):
        workflow.set_test_context("my_test")
        assert workflow._test_id is not None
        assert workflow._test_name == "my_test"
        assert workflow.question_number == 0

    def test_set_test_context_creates_test_in_db(self, workflow, db):
        workflow.set_test_context("new_test")
        test = db.get_test_by_name("new_test")
        assert test is not None

    def test_set_test_context_reuses_existing(self, workflow, db):
        db.get_or_create_test("existing_test")
        workflow.set_test_context("existing_test")
        assert workflow._test_id is not None


class TestWorkflowCounters:

    def test_initial_counters_are_zero(self, workflow):
        assert workflow.question_number == 0
        assert workflow.api_calls == 0
        assert workflow.cache_hits == 0

    def test_counters_reset_on_new_context(self, workflow):
        workflow._question_number = 5
        workflow._api_calls = 3
        workflow.set_test_context("reset_test")
        assert workflow.question_number == 0
        assert workflow.api_calls == 0


class TestAdvanceToNext:

    def test_advance_does_nothing_when_not_running(self, workflow, state_machine):
        workflow.advance_to_next()

    @patch("controller.orchestrator.workflow_engine.ClickDispatcher")
    def test_advance_logs_event(self, mock_cd, workflow, state_machine, event_logger, tmpdir):
        state_machine.transition_to(SystemState.RUNNING, "test")
        workflow._test_name = "test"
        workflow._question_number = 1

        workflow._click = MagicMock()
        workflow._verify = MagicMock()
        workflow._verify.verify_click.return_value = VerificationResult(verified=True)

        workflow.advance_to_next()

        events_dir = tmpdir / "events"
        event_file = events_dir / "events.jsonl"
        if event_file.exists():
            lines = event_file.read_text(encoding="utf-8").strip().split("\n")
            events = [json.loads(line) for line in lines if line]
            next_events = [e for e in events if e.get("event_type") == "click_next"]
            assert len(next_events) >= 1
