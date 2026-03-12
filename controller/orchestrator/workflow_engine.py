"""
Workflow engine.

Implements the main question-processing loop described in
Architecture Spec Section 17:

    1. Capture screenshot
    2. Validate screen (fail-safe)
    3. Detect scrolling requirement
    4. Capture additional frames if needed
    5. Stitch frames into composite image
    6. Send to Grok AI
    7. Parse response
    8. Run answer decision engine
    9. Handle conflicts if any
    10. Dispatch click command
    11. Verify click
    12. Click NEXT
    13. Log everything

Each step is logged and artifacts are saved for replay (Canonical Law 2, 11).
"""

import json
import time
import threading
from pathlib import Path
from typing import Optional

from controller.ai_pipeline.grok_client import query_grok, GrokAPIError
from controller.ai_pipeline.gemini_client import query_gemini, GeminiAPIError
from controller.ai_pipeline.ollama_client import (
    check_needs_scroll,
    check_is_answered,
    check_screen_state,
    OllamaAPIError
)
from controller.ai_pipeline.response_parser import GrokResponse, ParseError
from controller.config import LOCAL_AI_ASSIST_ENABLED, OLLAMA_MODEL, GROK_MODEL, GEMINI_MODEL, DEFAULT_AI_PROVIDER
from controller.answer_engine.decision_engine import (
    decide_answer,
    AnswerDecision,
    DecisionOutcome,
)
from controller.alerts.alert_manager import AlertManager, AlertType, OperatorDecision
from controller.capture_pipeline.image_receiver import ImageReceiver
from controller.capture_pipeline.image_stitcher import ImageStitcher
from controller.capture_pipeline.scroll_detector import ScrollDetector
from controller.capture_pipeline.screen_validator import ScreenValidator
from controller.capture_pipeline.image_preprocessor import ImagePreprocessor
from controller.hardware_control.click_dispatcher import ClickDispatcher
from controller.hardware_control.verification_engine import VerificationEngine
from controller.orchestrator.state_machine import StateMachine, SystemState
from controller.utils.logger import get_logger, EventLogger
from controller.utils.timer import ExecutionTimer
from database.db_manager import DatabaseManager

logger = get_logger("workflow_engine")

MAX_SCROLL_FRAMES = 3
SCROLL_FRAME_TIMEOUT = 10  # seconds


class WorkflowEngine:
    """
    Executes the main question-processing workflow loop.

    Depends on all subsystems being initialized and injected.
    """

    def __init__(
        self,
        state_machine: StateMachine,
        db: DatabaseManager,
        alert_manager: AlertManager,
        click_dispatcher: ClickDispatcher,
        verification_engine: VerificationEngine,
        image_receiver: ImageReceiver,
        event_logger: EventLogger,
    ) -> None:
        self._sm = state_machine
        self._db = db
        self._alerts = alert_manager
        self._click = click_dispatcher
        self._verify = verification_engine
        self._receiver = image_receiver
        self._event_log = event_logger
        self._stitcher = ImageStitcher()
        self._scroll_detector = ScrollDetector()
        self._screen_validator = ScreenValidator()
        self._preprocessor = ImagePreprocessor()

        self._test_id: Optional[int] = None
        self._test_name: Optional[str] = None
        self._question_number = 0
        self._api_calls = 0
        self._cache_hits = 0
        self._image_hash_hits = 0

        # Scroll-frame delivery mechanism
        self._scroll_frame_event = threading.Event()
        self._scroll_frame_event.set()  # Start set (not waiting)
        self._scroll_frame_data: Optional[bytes] = None
        self._is_waiting_flag: bool = False
        self._request_capture_callback: Optional[callable] = None
        self._ai_provider: str = DEFAULT_AI_PROVIDER  # "grok" or "gemini"

    def set_capture_callback(self, callback) -> None:
        """Set callback to request capture from the phone."""
        self._request_capture_callback = callback

    def set_ai_provider(self, provider: str) -> None:
        """Set the active AI provider for primary question solving."""
        provider = provider.lower()
        if provider not in ("grok", "gemini"):
            logger.error("Invalid AI provider: %s (must be 'grok' or 'gemini')", provider)
            return
        self._ai_provider = provider
        logger.info("AI provider set to: %s", provider)

    @property
    def ai_provider(self) -> str:
        return self._ai_provider

    @property
    def question_number(self) -> int:
        return self._question_number

    @property
    def api_calls(self) -> int:
        return self._api_calls

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    @property
    def image_hash_hits(self) -> int:
        return self._image_hash_hits

    @property
    def is_waiting_for_scroll(self) -> bool:
        """True if the engine is currently blocking for a scroll capture."""
        return self._is_waiting_flag

    def set_test_context(self, test_name: str) -> None:
        """Load or create the test context."""
        test = self._db.get_or_create_test(test_name)
        self._test_id = test["test_id"]
        self._test_name = test_name
        self._question_number = 0
        self._api_calls = 0
        self._cache_hits = 0
        logger.info("Test context set: %s (id=%d)", test_name, self._test_id)

    def receive_scroll_frame(self, image_data: bytes) -> None:
        """Called by system_controller when a scroll frame image is received."""
        self._scroll_frame_data = image_data
        self._scroll_frame_event.set()

    def process_question(self, image_data: bytes) -> Optional[AnswerDecision]:
        """
        Process a single question through the full pipeline.

        Args:
            image_data: Raw JPEG bytes of the captured screenshot.

        Returns:
            AnswerDecision if processing completed, or None if paused/error.
        """
        if self._sm.state != SystemState.RUNNING:
            logger.warning("Cannot process question — state is %s", self._sm.state.value)
            return None

        if self._test_id is None:
            logger.error("No test context set")
            return None

        self._question_number += 1
        logger.info("=== Processing question %d ===", self._question_number)

        with ExecutionTimer(f"question_{self._question_number}"):
            # Step 1: Receive and save image
            image_path = self._receiver.receive_image(image_data)

            # Step 2: Validate screen
            if LOCAL_AI_ASSIST_ENABLED:
                screen_state = check_screen_state(image_path)
                if screen_state not in ("QUESTION", "OTHER"):
                    self._sm.force_error(f"Abnormal screen detected: {screen_state}")
                    self._alerts.raise_alert(
                        AlertType.UNEXPECTED_SCREEN,
                        f"Unexpected screen detected: {screen_state}",
                    )
                    self._log_event("screen_validation_failed", {"issues": screen_state})
                    return None
            else:
                validation = self._screen_validator.validate(image_path)
                if not validation.valid:
                    self._sm.force_error(f"Screen validation failed: {validation.issues}")
                    self._alerts.raise_alert(
                        AlertType.UNEXPECTED_SCREEN,
                        f"Unexpected screen detected: {validation.issues}",
                    )
                    self._log_event("screen_validation_failed", {"issues": validation.issues})
                    return None

            # Step 3: Detect scrolling and capture additional frames
            # Use Local AI for scroll check if enabled
            if LOCAL_AI_ASSIST_ENABLED:
                needs_scroll = check_needs_scroll(image_path)
                scroll_direction = "right" # Default direction for stitched questions
            else:
                scroll_result = self._scroll_detector.detect(image_path)
                needs_scroll = scroll_result.needs_scroll
                scroll_direction = scroll_result.direction

            frames = [image_path]
            if needs_scroll:
                self._log_event("scroll_detected", {"direction": scroll_direction})
                additional = self._capture_scroll_frames(scroll_direction)
                frames.extend(additional)

            # Step 4: Stitch (or copy single frame)
            stitched_path = image_path.parent / f"stitched_{self._question_number:04d}.jpg"
            self._stitcher.stitch(frames, stitched_path)

            # Step 5: Preprocess
            self._preprocessor.preprocess(stitched_path)

            # Step 5.5: Image-hash DB-first lookup (no AI call on hit)
            image_phash = self._compute_image_phash(stitched_path)
            cached_question = None
            if image_phash is not None:
                cached_question = self._db.lookup_by_image_phash(self._test_id, image_phash)
                if cached_question:
                    logger.info(
                        "Image-hash DB HIT: question_id=%d (test_id=%d)",
                        cached_question["question_id"],
                        self._test_id,
                    )
                    self._image_hash_hits += 1

            ai_response = None
            ai_model_used = ""

            # Step 6: Query AI (dispatch to active provider) — only if no image-hash hit
            try:
                if cached_question is None:
                    if self._ai_provider == "gemini":
                        logger.info("Querying cloud Gemini AI (%s)", GEMINI_MODEL)
                        ai_response = query_gemini(stitched_path)
                        ai_model_used = GEMINI_MODEL
                    else:
                        logger.info("Querying cloud Grok AI (%s)", GROK_MODEL)
                        ai_response = query_grok(stitched_path)
                        ai_model_used = GROK_MODEL

                    self._api_calls += 1
                    self._log_event("ai_response", {
                        "provider": self._ai_provider,
                        "model": ai_model_used,
                        "question": ai_response.question[:100],
                        "answer": ai_response.answer,
                        "answer_content": ai_response.answer_content[:100],
                    })
                    self._save_ai_response(ai_response, ai_model_used)
            except (GrokAPIError, GeminiAPIError, OllamaAPIError, ParseError) as e:
                self._sm.force_error(f"AI processing failed: {e}")
                self._alerts.raise_alert(
                    AlertType.AI_PARSE_FAILURE,
                    f"AI processing failed: {e}",
                )
                self._log_event("ai_error", {"error": str(e)})
                return None

            # Step 7: Run decision engine or DB-only decision if we have an image-hash hit
            if cached_question is not None:
                db_answer = cached_question.get("correct_answer", "")
                answer_letter = cached_question.get("answer_letter", "")
                if not answer_letter:
                    logger.error(
                        "Cached question %d has empty answer_letter; cannot use image-hash fast path",
                        cached_question.get("question_id"),
                    )
                    return None

                logger.info(
                    "Using DB answer via image-hash fast path: letter=%s",
                    answer_letter,
                )
                decision = AnswerDecision(
                    outcome=DecisionOutcome.CLICK,
                    click_letter=answer_letter,
                    source="database_image_hash",
                    question_id=cached_question.get("question_id"),
                )
                self._cache_hits += 1
            else:
                decision = decide_answer(self._db, self._test_id, ai_response)  # type: ignore[arg-type]

            if decision.source and decision.source != "ai_new":
                self._cache_hits += 1

            # Step 8: Handle outcome
            if decision.outcome == DecisionOutcome.CONFLICT:
                self._sm.force_error("Answer conflict detected")
                self._alerts.raise_alert(
                    AlertType.AI_CONFLICT,
                    decision.conflict.message,
                    data=decision.conflict.to_alert_payload(),
                )
                self._log_event("conflict", decision.conflict.to_alert_payload())
                return decision

            if decision.outcome == DecisionOutcome.ERROR:
                self._sm.force_error(decision.error_message or "Decision error")
                return decision

            # Step 9: Execute click
            if decision.click_letter:
                self._execute_click_with_verification(decision.click_letter)
                self._log_event("answer_decision", {
                    "question_number": self._question_number,
                    "click_letter": decision.click_letter,
                    "source": decision.source,
                    "question_id": decision.question_id,
                })

            # Step 10: Store full question snapshot (Canonical Law 10)
            if decision.question_id is not None:
                if ai_response is not None:
                    ai_response_json = json.dumps({
                        "model": ai_model_used,
                        "question": ai_response.question,
                        "options": {
                            "A": ai_response.options.A,
                            "B": ai_response.options.B,
                            "C": ai_response.options.C,
                            "D": ai_response.options.D,
                        },
                        "answer": ai_response.answer,
                        "answer_content": ai_response.answer_content,
                    }, ensure_ascii=False)
                    selected_answer_text = ai_response.answer_content
                else:
                    ai_response_json = ""
                    # For image-hash fast path, selected answer is the DB correct_answer
                    if cached_question is not None:
                        selected_answer_text = cached_question.get("correct_answer", "")
                    else:
                        selected_answer_text = ""

                self._db.store_snapshot(
                    question_id=decision.question_id,
                    run_id=self._receiver.run_dir.name,
                    screenshot_path=str(image_path),
                    ai_response=ai_response_json,
                    selected_answer=selected_answer_text,
                    decision_source=decision.source or "unknown",
                    image_phash=image_phash,
                )

            return decision

    def advance_to_next(self) -> None:
        """
        Click NEXT to advance to the next question.
        Follows Hardware Input Transaction flow (Canonical Law 5):
        send click → verify → retry → alert on failure.
        """
        if self._sm.state != SystemState.RUNNING:
            return
        logger.info("Advancing to next question")
        self._click.click_next()
        self._log_event("click_next", {"after_question": self._question_number})

        result = self._verify.verify_click("NEXT")
        if result.verified:
            logger.info("NEXT click verified")
            return

        logger.warning("NEXT click verification failed — retrying")
        self._click.click_next()
        result = self._verify.verify_click("NEXT")

        if result.verified:
            logger.info("NEXT retry click verified")
            return

        logger.error("NEXT click verification FAILED after retry")
        self._sm.force_error("Input verification failed for NEXT button")
        self._alerts.raise_alert(
            AlertType.VERIFICATION_FAILURE,
            "NEXT button click verification failed after retry",
        )

    def _execute_click_with_verification(self, letter: str) -> None:
        """
        Execute a click and verify it (Hardware Input Transaction — Canonical Law 5).

        Retry once on failure, then alert.
        """
        self._click.click_option(letter)
        
        # Give UI time to update
        time.sleep(1.0)
        
        # Verify click
        verified = self._verify_option_click(letter)

        if verified:
            logger.info("Click verified for option %s", letter)
            return

        logger.warning("Click verification failed for %s — retrying", letter)
        self._click.click_option(letter)
        time.sleep(1.0)
        verified = self._verify_option_click(letter)

        if verified:
            logger.info("Retry click verified for option %s", letter)
            return

        logger.error("Click verification FAILED after retry for option %s", letter)
        self._sm.force_error(f"Input verification failed for option {letter}")
        self._alerts.raise_alert(
            AlertType.VERIFICATION_FAILURE,
            f"Click verification failed for option {letter} after retry",
        )

    def _verify_option_click(self, letter: str) -> bool:
        """
        Verify whether an option click was registered.

        Uses Local AI (Qwen) if enabled, otherwise falls back
        to the CV-based verification engine.
        """
        if LOCAL_AI_ASSIST_ENABLED:
            image_bytes = self._receiver.capture_immediate()
            if image_bytes:
                verify_path = self._receiver.receive_image(image_bytes)
                verified, _ = check_is_answered(verify_path)
                return verified
            return False
        else:
            return self._verify.verify_click(letter).verified

    def _capture_scroll_frames(self, direction: str) -> list[Path]:
        """
        Scroll the exam screen and capture additional frames.

        Args:
            direction: "left" or "right"

        Returns:
            List of Paths to additional frame images.
        """
        additional_frames = []

        for i in range(MAX_SCROLL_FRAMES):
            logger.info("Scroll frame %d/%d — scrolling %s", i + 1, MAX_SCROLL_FRAMES, direction)

            # Send scroll command
            if direction == "right":
                self._click.scroll_right()
            else:
                self._click.scroll_left()

            # Request a new capture from the phone
            self._scroll_frame_event.clear()
            self._scroll_frame_data = None
            # Set a flag to explicit mark as waiting since initial state is also clear
            self._is_waiting_flag = True

            if self._request_capture_callback:
                self._request_capture_callback()

            # Wait for the frame to arrive
            arrived = self._scroll_frame_event.wait(timeout=SCROLL_FRAME_TIMEOUT)
            self._is_waiting_flag = False

            if not arrived or self._scroll_frame_data is None:
                logger.warning("Scroll frame %d timed out after %ds", i + 1, SCROLL_FRAME_TIMEOUT)
                break

            # Save the scroll frame
            frame_path = self._receiver.receive_image(self._scroll_frame_data)
            additional_frames.append(frame_path)
            logger.info("Scroll frame %d captured: %s", i + 1, frame_path)

            # Check if more scrolling is needed
            scroll_result = self._scroll_detector.detect(frame_path)
            if not scroll_result.needs_scroll:
                logger.info("No more scrolling needed after frame %d", i + 1)
                break

        self._log_event("scroll_complete", {"frames_captured": len(additional_frames)})
        return additional_frames

    def _log_event(self, event_type: str, data: dict) -> None:
        data["question_number"] = self._question_number
        data["test_name"] = self._test_name
        self._event_log.log_event(event_type, data)

    def _save_ai_response(self, response: GrokResponse, model_used: str) -> None:
        """Save AI response JSON for replay."""
        ai_dir = self._receiver.run_dir / "ai_responses"
        ai_dir.mkdir(parents=True, exist_ok=True)
        path = ai_dir / f"ai_response_{self._question_number:04d}.json"
        data = {
            "model": model_used,
            "question": response.question,
            "options": {
                "A": response.options.A,
                "B": response.options.B,
                "C": response.options.C,
                "D": response.options.D,
            },
            "answer": response.answer,
            "answer_content": response.answer_content,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.debug("AI response saved: %s", path)

    def _compute_image_phash(self, image_path: Path, hash_size: int = 8) -> str | None:
        """
        Compute a 64-bit perceptual hash (pHash) for the stitched question image.

        Returns a 64-character '0'/'1' string, or None if OpenCV is unavailable.
        """
        try:
            import cv2
            import numpy as np
        except ImportError:
            logger.warning("OpenCV not available — image hash lookup disabled")
            return None

        img = cv2.imread(str(image_path))
        if img is None:
            logger.warning("Cannot read image for pHash: %s", image_path)
            return None

        resized = cv2.resize(img, (hash_size * 4, hash_size * 4))
        if len(resized.shape) == 3:
            resized = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

        dct = cv2.dct(resized.astype(np.float32))
        dct_low = dct[:hash_size, :hash_size]
        median = float(np.median(dct_low))
        bits = (dct_low > median).astype(int).flatten()
        return "".join(str(b) for b in bits)
