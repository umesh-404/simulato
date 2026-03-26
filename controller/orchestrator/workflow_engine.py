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
    locate_next_button_grid,
    locate_option_target,
    locate_next_button_target,
    OllamaAPIError
)
from controller.ai_pipeline.response_parser import GrokResponse, ParseError
from controller.config import (
    LOCAL_AI_ASSIST_ENABLED,
    OCR_LAYOUT_PRIMARY_ENABLED,
    OLLAMA_MODEL,
    GROK_MODEL,
    GEMINI_MODEL,
    DEFAULT_AI_PROVIDER,
    GROK_API_KEY,
    GEMINI_API_KEY,
    VERIFY_FRAME_TIMEOUT_SECONDS,
)
from controller.answer_engine.decision_engine import (
    decide_answer,
    AnswerDecision,
    DecisionOutcome,
)
from controller.answer_engine.option_matcher import match_option_by_content
from controller.question_engine.question_matcher import match_question
from controller.alerts.alert_manager import AlertManager, AlertType, OperatorDecision
from controller.capture_pipeline.image_receiver import ImageReceiver
from controller.capture_pipeline.image_stitcher import ImageStitcher
from controller.capture_pipeline.scroll_detector import ScrollDetector
from controller.capture_pipeline.screen_validator import ScreenValidator
from controller.capture_pipeline.image_preprocessor import ImagePreprocessor
from controller.capture_pipeline.ocr_layout_analyzer import OCRLayoutAnalyzer, OCRLayoutResult
from controller.capture_pipeline.exam_layout import ExamLayoutDetector
from controller.capture_pipeline.option_detector import OptionDetector
from controller.hardware_control.click_dispatcher import ClickDispatcher
from controller.hardware_control.verification_engine import VerificationEngine, VerificationResult
from controller.orchestrator.state_machine import StateMachine, SystemState
from controller.utils.logger import get_logger, EventLogger
from controller.utils.timer import ExecutionTimer
from database.db_manager import DatabaseManager

logger = get_logger("workflow_engine")

MAX_SCROLL_FRAMES = 3
SCROLL_FRAME_TIMEOUT = 10  # seconds
VERIFY_FRAME_TIMEOUT = VERIFY_FRAME_TIMEOUT_SECONDS


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
        self._ocr = OCRLayoutAnalyzer()
        self._latest_ocr_layout: Optional[OCRLayoutResult] = None
        self._latest_interaction_ocr_layout: Optional[OCRLayoutResult] = None
        self._latest_preprocessed_image_path: Optional[Path] = None

        self._test_id: Optional[int] = None
        self._test_name: Optional[str] = None
        self._question_number = 0
        self._api_calls = 0
        self._cache_hits = 0
        self._image_hash_hits = 0
        self._expecting_next_change: bool = False
        self._no_change_after_next_count: int = 0
        self._last_raw_phash: str | None = None
        self._last_answered_question_id: int | None = None

        # Scroll-frame delivery mechanism
        self._scroll_frame_event = threading.Event()
        self._scroll_frame_event.set()  # Start set (not waiting)
        self._scroll_frame_data: Optional[bytes] = None
        self._is_waiting_flag: bool = False
        self._mapping_frame_event = threading.Event()
        self._mapping_frame_event.set()
        self._mapping_frame_data: Optional[bytes] = None
        self._is_waiting_mapping_flag: bool = False
        self._verification_frame_event = threading.Event()
        self._verification_frame_event.set()
        self._verification_frame_data: Optional[bytes] = None
        self._is_waiting_verification_flag: bool = False
        self._request_capture_callback: Optional[callable] = None
        self._ai_provider: str = DEFAULT_AI_PROVIDER  # "grok" or "gemini"
        self._last_verification_timed_out: bool = False
        self._last_option_click_target_norm: tuple[float, float] | None = None
        self._current_answer_text_for_click: str = ""
        self._last_dispatched_click_letter: str | None = None

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

    @property
    def is_waiting_for_verification(self) -> bool:
        """True if the engine is currently waiting for a verification capture."""
        return self._is_waiting_verification_flag

    @property
    def is_waiting_for_mapping(self) -> bool:
        """True if the engine is currently waiting for a post-AI mapping capture."""
        return self._is_waiting_mapping_flag

    def set_test_context(self, test_name: str) -> None:
        """Load or create the test context."""
        test = self._db.get_or_create_test(test_name)
        self._test_id = test["test_id"]
        self._test_name = test_name
        self._question_number = 0
        self._api_calls = 0
        self._cache_hits = 0
        self._image_hash_hits = 0
        self._expecting_next_change = False
        self._no_change_after_next_count = 0
        self._last_raw_phash = None
        self._last_answered_question_id = None
        self._latest_ocr_layout = None
        self._latest_interaction_ocr_layout = None
        self._latest_preprocessed_image_path = None
        self._current_answer_text_for_click = ""
        self._last_dispatched_click_letter = None
        self._mapping_frame_data = None
        self._is_waiting_mapping_flag = False
        self._mapping_frame_event.set()
        logger.info("Test context set: %s (id=%d)", test_name, self._test_id)

    def receive_scroll_frame(self, image_data: bytes) -> None:
        """Called by system_controller when a scroll frame image is received."""
        self._scroll_frame_data = image_data
        self._scroll_frame_event.set()

    def receive_verification_frame(self, image_data: bytes) -> None:
        """Called by system_controller when a verification frame is received."""
        self._verification_frame_data = image_data
        self._verification_frame_event.set()

    def receive_mapping_frame(self, image_data: bytes) -> None:
        """Called by system_controller when a post-AI mapping frame is received."""
        self._mapping_frame_data = image_data
        self._mapping_frame_event.set()

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
        # Prevent stale layout/target coordinates from previous question.
        self._latest_ocr_layout = None
        self._latest_interaction_ocr_layout = None

        #region agent log
        from controller.utils.debug_ndjson import dbg as _dbg
        _dbg(
            location="controller/orchestrator/workflow_engine.py:process_question",
            message="process_question start",
            data={
                "state": self._sm.state.value,
                "question_number": self._question_number,
                "test_id": self._test_id,
                "ocr_enabled": bool(OCR_LAYOUT_PRIMARY_ENABLED),
                "local_ai_enabled": bool(LOCAL_AI_ASSIST_ENABLED),
            },
            hypothesisId="H1",
        )
        #endregion agent log

        with ExecutionTimer(f"question_{self._question_number}"):
            # Step 1: Receive and save image
            image_path = self._receiver.receive_image(image_data)
            initial_preprocessed_path = image_path
            #region agent log
            _dbg(
                location="controller/orchestrator/workflow_engine.py:process_question",
                message="image received",
                data={"image_path": str(image_path)},
                hypothesisId="H1",
            )
            #endregion agent log

            # End-of-test detection: after NEXT, the question should change.
            # If we keep receiving essentially the same screen after NEXT, alert and pause.
            raw_phash = self._compute_image_phash(image_path)
            if self._expecting_next_change and raw_phash and self._last_raw_phash:
                hamming = sum(
                    a != b for a, b in zip(raw_phash, self._last_raw_phash)
                )
                same_screen = hamming <= 6
                if same_screen:
                    self._no_change_after_next_count += 1
                    logger.warning(
                        "No screen change detected after NEXT (hamming=%d, count=%d)",
                        hamming,
                        self._no_change_after_next_count,
                    )
                    if self._no_change_after_next_count >= 2:
                        self._sm.force_error("Test complete or NEXT no longer advances")
                        self._alerts.raise_alert(
                            AlertType.TEST_COMPLETE,
                            "Possible end of test: screen did not change after NEXT. Please check the exam UI.",
                        )
                        return None
                else:
                    self._expecting_next_change = False
                    self._no_change_after_next_count = 0

            if raw_phash:
                self._last_raw_phash = raw_phash

            # Step 2: Validate screen
            if LOCAL_AI_ASSIST_ENABLED:
                # Local AI tasks are more robust when they see an anchored, exam-aligned region.
                initial_preprocessed_path = self._preprocessor.preprocess(image_path)
                screen_state = check_screen_state(initial_preprocessed_path)
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
                    # False-negative guard: some valid exam screens with light themes
                    # can fail low edge-density checks. If layout + options are found,
                    # proceed deterministically instead of forcing ERROR.
                    if self._is_exam_screen_despite_low_density(image_path, validation):
                        logger.warning(
                            "Bypassing low-density screen validation failure because exam layout/options were detected"
                        )
                    else:
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
                needs_scroll = check_needs_scroll(initial_preprocessed_path)
                scroll_direction = "right" # Default direction for stitched questions
            else:
                # Prefer panel-aware structural detection when layout is available.
                needs_scroll = False
                scroll_direction = "down"
                try:
                    layout_for_scroll = None
                    scroll_ocr_res = None
                    if OCR_LAYOUT_PRIMARY_ENABLED and self._latest_ocr_layout is not None:
                        layout_for_scroll = self._latest_ocr_layout.layout
                    if layout_for_scroll is None:
                        fallback_layout_res = self._ocr.analyze(initial_preprocessed_path)
                        scroll_ocr_res = fallback_layout_res
                        layout_for_scroll = fallback_layout_res.layout if fallback_layout_res is not None else None
                    if layout_for_scroll is not None:
                        dual = self._scroll_detector.detect_dual(image_path, layout_for_scroll)
                        # Respect detector verdict; only override for clearly
                        # truncated panels (confidence >= 0.35 strongly suggests
                        # question text is cut off).
                        needs_scroll = bool(dual.question.needs_scroll or dual.question.confidence >= 0.35)
                        if not needs_scroll and scroll_ocr_res is not None:
                            needs_scroll = self._question_panel_text_truncated(scroll_ocr_res)
                        scroll_direction = "down" if needs_scroll else None
                    else:
                        scroll_result = self._scroll_detector.detect(image_path)
                        needs_scroll = scroll_result.needs_scroll
                        scroll_direction = scroll_result.direction
                except Exception:
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
            preprocessed_path = self._preprocessor.preprocess(stitched_path)
            # Keep a separate preprocessed frame for interaction targeting.
            # Click/scroll/NEXT should target the current visible frame,
            # not the vertically stitched composite.
            interaction_preprocessed_path = self._preprocessor.preprocess(frames[-1])
            self._latest_preprocessed_image_path = interaction_preprocessed_path
            #region agent log
            _dbg(
                location="controller/orchestrator/workflow_engine.py:process_question",
                message="preprocess complete",
                data={
                    "stitched_path": str(stitched_path),
                    "preprocessed_path": str(preprocessed_path),
                },
                hypothesisId="H1",
            )
            #endregion agent log

            # Persist preprocess meta into the event log for replay/debug.
            meta_path = preprocessed_path.parent / f"{preprocessed_path.stem}.preprocess_meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    self._log_event("preprocess_meta", {"stitched": True, "header_anchor": meta.get("header_anchor")})
                except Exception:
                    pass

            # Step 5.25: OCR layout pass (whole screen, deterministic)
            if OCR_LAYOUT_PRIMARY_ENABLED:
                self._latest_ocr_layout = self._ocr.analyze(preprocessed_path)
                self._latest_interaction_ocr_layout = self._ocr.analyze(interaction_preprocessed_path)
            else:
                self._latest_ocr_layout = None
                self._latest_interaction_ocr_layout = None

            # Detect question number from the raw (non-preprocessed) image
            # header, which contains "Question No : N / M".
            raw_ocr = self._ocr.analyze(image_path) if OCR_LAYOUT_PRIMARY_ENABLED else None
            if raw_ocr is not None:
                q_num = raw_ocr.detect_question_number()
                if q_num is not None:
                    current_q, total_q = q_num
                    self._question_number = current_q
                    logger.info(
                        "Detected question number: %d / %d",
                        current_q, total_q,
                    )
                    self._log_event("question_number_detected", {
                        "current": current_q,
                        "total": total_q,
                    })

            #region agent log
            _dbg(
                location="controller/orchestrator/workflow_engine.py:process_question",
                message="ocr_layout done",
                data={
                    "ocr_layout_available": self._latest_ocr_layout is not None,
                    "ocr_words": (len(self._latest_ocr_layout.words) if self._latest_ocr_layout is not None else 0),
                    "question_number": self._question_number,
                },
                hypothesisId="H2",
            )
            #endregion agent log

            # Step 5.5: Image-hash DB-first lookup (no AI call on hit)
            image_phash = self._compute_image_phash(stitched_path)
            cached_question = None
            if image_phash is not None:
                cached_question = self._db.lookup_by_image_phash(self._test_id, image_phash)
                if cached_question is None:
                    cached_question = self._db.lookup_by_image_phash_near(self._test_id, image_phash, max_distance=3)
                if cached_question:
                    # Validate cache hit against live on-screen content
                    # to prevent false identity reuse across different questions
                    # that happen to hash similarly.
                    if not self._validate_cache_hit(cached_question):
                        logger.warning(
                            "Image-hash cache hit REJECTED by content validation "
                            "(question_id=%d, test_id=%d)",
                            cached_question["question_id"],
                            self._test_id,
                        )
                        cached_question = None
                    else:
                        logger.info(
                            "Image-hash DB HIT (validated): question_id=%d (test_id=%d)",
                            cached_question["question_id"],
                            self._test_id,
                        )
                        self._image_hash_hits += 1

            # Step 5.6: OCR-text DB pre-check (no cloud call if cached by text/options)
            ocr_cached_decision = None
            if cached_question is None:
                ocr_cached_decision = self._try_db_decision_from_ocr()
            #region agent log
            _dbg(
                location="controller/orchestrator/workflow_engine.py:process_question",
                message="db image_phash lookup",
                data={
                    "image_phash_present": image_phash is not None,
                    "cached_hit": cached_question is not None,
                    "question_id": (cached_question.get("question_id") if cached_question else None),
                },
                hypothesisId="H4",
            )
            #endregion agent log

            ai_response = None
            ai_model_used = ""
            answer_text_for_click = ""

            # Step 6: Query AI (dispatch to active provider) — only if no image-hash hit
            try:
                if cached_question is None:
                    if ocr_cached_decision is None:
                        ai_response, ai_model_used, provider_used = self._query_primary_with_fallback(preprocessed_path)
                        self._api_calls += 1
                        self._log_event("ai_response", {
                            "provider": provider_used,
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
                answer_text_for_click = db_answer or ""
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
                remapped = self._remap_letter_by_option_content(
                    db_answer_text=db_answer,
                    fallback_letter=answer_letter,
                )
                decision = AnswerDecision(
                    outcome=DecisionOutcome.CLICK,
                    click_letter=remapped,
                    source="database_image_hash",
                    question_id=cached_question.get("question_id"),
                )
            elif ocr_cached_decision is not None:
                decision = ocr_cached_decision
                if decision.match_result is not None:
                    answer_text_for_click = (decision.match_result.correct_answer or "").strip()
            else:
                decision = decide_answer(self._db, self._test_id, ai_response)  # type: ignore[arg-type]
                answer_text_for_click = (ai_response.answer_content if ai_response is not None else "") or ""
                # Always remap by live on-screen option content to handle shuffled options.
                if decision.click_letter and ai_response is not None:
                    decision.click_letter = self._remap_letter_by_option_content(
                        db_answer_text=ai_response.answer_content,
                        fallback_letter=decision.click_letter,
                    )

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

            # Use stitched image for AI solve only. Before click dispatch, capture
            # a fresh frame and rebuild radio-button mapping from that live frame.
            if decision.click_letter:
                self._refresh_interaction_targets_post_ai()

                # Set expected option count on the interaction layout so the
                # option detector trims phantom circles beyond the real count.
                expected_options = self._compute_expected_option_count(ai_response, cached_question)
                if expected_options is not None:
                    for layout_obj in (self._latest_interaction_ocr_layout, self._latest_ocr_layout):
                        if layout_obj is not None and hasattr(layout_obj, 'set_max_options'):
                            layout_obj.set_max_options(expected_options)

            # Step 9: Execute click
            # Guard: if this is the same question we just answered (NEXT
            # failed to navigate), the option is already selected on screen.
            # Re-clicking it would deselect it (toggle behaviour).
            already_answered = (
                decision.question_id is not None
                and decision.question_id == self._last_answered_question_id
            )
            if already_answered:
                logger.warning(
                    "Same question_id=%d already answered — skipping option click to avoid deselection",
                    decision.question_id,
                )
            elif decision.click_letter:
                self._current_answer_text_for_click = answer_text_for_click.strip()
                self._execute_click_with_verification(decision.click_letter)

            if decision.click_letter or already_answered:
                self._log_event("answer_decision", {
                    "question_number": self._question_number,
                    "click_letter": decision.click_letter,
                    "dispatched_letter": self._last_dispatched_click_letter,
                    "source": decision.source,
                    "question_id": decision.question_id,
                    "skipped_click": already_answered,
                })
            if decision.question_id is not None:
                self._last_answered_question_id = decision.question_id

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
                            "E": ai_response.options.E,
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
        send click → wait for navigation → verify screen changed → retry → alert.
        """
        if self._sm.state != SystemState.RUNNING:
            return
        logger.info("Advancing to next question")

        # Capture a reference frame *before* clicking NEXT so we can
        # verify the screen actually changed afterwards.
        pre_next_path = self._capture_single_frame_for_ref()

        self._click_next_best_target()
        self._log_event("click_next", {"after_question": self._question_number})

        # Browser needs time to process the click and navigate.
        time.sleep(2.5)

        result = self._verify_next_click_by_change(pre_next_path)
        if result.verified:
            logger.info("NEXT click verified (screen changed)")
            self._expecting_next_change = True
            self._no_change_after_next_count = 0
            return

        # Passive re-check only (NO retry click).
        # A second NEXT click is far more dangerous (skips a question)
        # than a false "didn't navigate" verdict. If the first click
        # actually worked but verification was noisy, the next cycle's
        # pHash same-screen guard (L289-310) will catch the true state.
        logger.warning("NEXT click verification borderline — passive re-check")
        time.sleep(1.5)
        recheck = self._verify_next_click_by_change(pre_next_path)
        if recheck.verified:
            logger.info("NEXT re-check verified (screen changed)")
            self._expecting_next_change = True
            self._no_change_after_next_count = 0
            return

        # Optimistic pass: assume NEXT worked.
        # The next process_question() call will compare pHash of the
        # incoming frame against _last_raw_phash. If the screen truly
        # didn't change, _no_change_after_next_count increments and
        # triggers the end-of-test/stuck alert after 2 consecutive hits.
        logger.warning(
            "NEXT verification inconclusive after re-check — proceeding "
            "optimistically. Next cycle pHash guard will catch true failures."
        )
        self._expecting_next_change = True

    def _capture_single_frame_for_ref(self) -> Optional[Path]:
        """Capture a single frame for before/after comparison. Returns path or None."""
        self._verification_frame_event.clear()
        self._verification_frame_data = None
        self._is_waiting_verification_flag = True
        if self._request_capture_callback:
            self._request_capture_callback()
        arrived = self._verification_frame_event.wait(timeout=VERIFY_FRAME_TIMEOUT)
        self._is_waiting_verification_flag = False
        if not arrived or self._verification_frame_data is None:
            return None
        return self._receiver.receive_image(self._verification_frame_data)

    def _verify_next_click_by_change(self, pre_next_path: Optional[Path]) -> VerificationResult:
        """
        Verify NEXT click by checking the screen has changed.

        Compares a post-click capture against the pre-click reference,
        focusing on the question panel region for a stronger signal.
        Camera noise between two captures of the *same* screen can
        produce a full-image mean_diff of 2-4, so we compare only the
        question panel where content changes dramatically on navigation.
        """
        self._verification_frame_event.clear()
        self._verification_frame_data = None
        self._is_waiting_verification_flag = True
        if self._request_capture_callback:
            self._request_capture_callback()
        arrived = self._verification_frame_event.wait(timeout=VERIFY_FRAME_TIMEOUT)
        self._is_waiting_verification_flag = False

        if not arrived or self._verification_frame_data is None:
            logger.warning("NEXT verification capture timed out — assuming success")
            return VerificationResult(verified=True, details="next_capture_timeout_pass")

        post_path = self._receiver.receive_image(self._verification_frame_data)

        if pre_next_path is None:
            logger.info("No pre-NEXT reference frame — assuming NEXT succeeded")
            return VerificationResult(verified=True, details="no_pre_frame_pass")

        try:
            import cv2
            pre_img = cv2.imread(str(pre_next_path))
            post_img = cv2.imread(str(post_path))
            if pre_img is None or post_img is None:
                return VerificationResult(verified=True, details="unreadable_frames_pass")
            if pre_img.shape != post_img.shape:
                logger.info("NEXT verified: image dimensions changed")
                return VerificationResult(verified=True, details="dimension_change", confidence=1.0)

            # Compare question panel region only for a stronger signal.
            # The question text changes completely on navigation while the
            # rest of the UI (header, sidebar) stays mostly the same.
            q_diff = self._question_panel_diff(pre_img, post_img)
            full_diff = cv2.absdiff(pre_img, post_img)
            full_mean = float(full_diff.mean())

            if q_diff is not None:
                logger.info(
                    "NEXT verify: question_panel_diff=%.1f, full_diff=%.1f",
                    q_diff, full_mean,
                )
                # Question panel changes dramatically on navigation.
                # Camera noise on the same screen produces q_panel diffs
                # of 2-4; real page changes produce 5.5+.
                if q_diff > 5.0:
                    return VerificationResult(
                        verified=True,
                        details="question_panel_changed",
                        confidence=min(q_diff / 20.0, 1.0),
                    )
            else:
                logger.info("NEXT verify: full_diff=%.1f (no q-panel region)", full_mean)

            # Fallback to full-image diff with a higher threshold to
            # avoid false positives from camera noise (2-4 is normal noise).
            if full_mean > 6.0:
                logger.info("NEXT verified: full mean pixel diff = %.1f", full_mean)
                return VerificationResult(
                    verified=True,
                    details="screen_changed",
                    confidence=min(full_mean / 15.0, 1.0),
                )

            # Additional fallback: perceptual hash distance.
            # This helps when global brightness shifts keep mean diff low,
            # but the page content has actually changed.
            pre_hash = self._compute_image_phash(pre_next_path)
            post_hash = self._compute_image_phash(post_path)
            if pre_hash and post_hash:
                hamming = sum(a != b for a, b in zip(pre_hash, post_hash))
                logger.info("NEXT verify: pHash hamming distance=%d", hamming)
                if hamming >= 8:
                    return VerificationResult(
                        verified=True,
                        details="phash_changed",
                        confidence=min(hamming / 32.0, 1.0),
                    )

            logger.warning(
                "NEXT verification: screen did NOT change (full=%.1f, q_panel=%s)",
                full_mean,
                f"{q_diff:.1f}" if q_diff is not None else "N/A",
            )
            return VerificationResult(verified=False, details="no_screen_change", confidence=0.0)
        except Exception as e:
            logger.warning("NEXT verification error: %s — assuming success", e)
            return VerificationResult(verified=True, details="error_pass")

    def _question_panel_diff(self, pre_img, post_img) -> Optional[float]:
        """Compute mean pixel diff in the question panel region only."""
        try:
            import cv2
            from controller.capture_pipeline.exam_layout import ExamLayoutDetector
            h, w = pre_img.shape[:2]
            # Use a deterministic region: left 45% of the image, middle 60% vertically.
            # This covers the question panel on the exam layout without needing
            # full layout detection (which would be expensive).
            y1 = int(h * 0.15)
            y2 = int(h * 0.75)
            x1 = int(w * 0.10)
            x2 = int(w * 0.48)
            if y2 <= y1 or x2 <= x1:
                return None
            pre_region = pre_img[y1:y2, x1:x2]
            post_region = post_img[y1:y2, x1:x2]
            diff = cv2.absdiff(pre_region, post_region)
            return float(diff.mean())
        except Exception:
            return None

    def _click_next_best_target(self) -> None:
        """Click NEXT using the best available detection method.

        Priority:
        1. OCR layout result (uses layout detector rect → CV color → OCR word)
        2. Layout detector's next_button rect directly from the latest layout
        3. Local AI (Qwen) target localization
        4. Calibrated grid-map fallback
        """
        if OCR_LAYOUT_PRIMARY_ENABLED and self._latest_interaction_ocr_layout is not None:
            ocr_next = self._latest_interaction_ocr_layout.locate_next_target()
            if ocr_next is not None:
                logger.info("Using OCR-derived NEXT target (%.4f, %.4f)", ocr_next[0], ocr_next[1])
                self._click.click_at_normalized(ocr_next[0], ocr_next[1], command="CLICK_NEXT")
                return

            # Fallback: use layout detector's next_button rect directly.
            layout = self._latest_interaction_ocr_layout.layout
            if layout is not None and layout.next_button is not None:
                nb = layout.next_button
                ix = max(1, self._latest_interaction_ocr_layout.image_w - 1)
                iy = max(1, self._latest_interaction_ocr_layout.image_h - 1)
                nx = max(0.0, min(1.0, float(nb.x + nb.w // 2) / float(ix)))
                ny = max(0.0, min(1.0, float(nb.y + nb.h // 2) / float(iy)))
                logger.info("Using layout-detector NEXT button rect (%.4f, %.4f)", nx, ny)
                self._click.click_at_normalized(nx, ny, command="CLICK_NEXT")
                return

            # Last layout fallback: bottom-right corner of answer panel.
            if layout is not None and layout.answer_panel is not None:
                ap = layout.answer_panel
                ix = max(1, self._latest_interaction_ocr_layout.image_w - 1)
                iy = max(1, self._latest_interaction_ocr_layout.image_h - 1)
                nx = max(0.0, min(1.0, float(ap.x + int(ap.w * 0.90)) / float(ix)))
                ny = max(0.0, min(1.0, float(ap.y + int(ap.h * 0.96)) / float(iy)))
                logger.info("Using layout-derived NEXT fallback target (%.4f, %.4f)", nx, ny)
                self._click.click_at_normalized(nx, ny, command="CLICK_NEXT")
                return
        if LOCAL_AI_ASSIST_ENABLED and self._latest_preprocessed_image_path is not None:
            norm_target = locate_next_button_target(self._latest_preprocessed_image_path)
            if norm_target is not None:
                self._click.click_at_normalized(norm_target[0], norm_target[1], command="CLICK_NEXT")
                return
            visible, grid_pos = locate_next_button_grid(self._latest_preprocessed_image_path)
            if visible and grid_pos is not None:
                self._click.click_next_at_grid(grid_pos[0], grid_pos[1])
                return
        self._click.click_next()

    def _execute_click_with_verification(self, letter: str) -> None:
        """
        Execute a click and verify it (Hardware Input Transaction — Canonical Law 5).

        Retry with deterministic nearby radio-row fallbacks, then alert.
        """
        if self._sm.state != SystemState.RUNNING:
            logger.info("Skipping click execution for %s — state is %s", letter, self._sm.state.value)
            return
        logger.info("Click attempt 1 for intended option %s", letter)
        dispatched_letter = self._click_option_best_target(letter)
        self._last_dispatched_click_letter = dispatched_letter
        time.sleep(1.0)
        verified = self._verify_option_click(dispatched_letter)
        if verified:
            logger.info("Click verified for option %s (dispatched=%s)", letter, dispatched_letter)
            return
        if self._last_verification_timed_out:
            logger.warning(
                "Verification capture timed out while checking option %s; stopping retries",
                letter,
            )
            return

        logger.warning("Click verification failed for %s — checking if already selected before retry", letter)

        # CRITICAL: Before re-clicking, take a fresh screenshot and re-verify.
        # If the option IS already selected (first click worked, verification
        # was a false negative due to timing/crop), re-clicking would TOGGLE
        # the selection OFF — a destructive outcome worse than a missed click.
        time.sleep(0.5)
        pre_retry_verified = self._verify_option_click(dispatched_letter)
        if pre_retry_verified:
            logger.info(
                "Pre-retry check: option %s IS already selected — skipping re-click (first click worked, "
                "initial verification was a false negative)",
                letter,
            )
            return
        if self._last_verification_timed_out:
            logger.warning(
                "Pre-retry verification capture timed out for option %s; assuming first click worked",
                letter,
            )
            return

        logger.info("Pre-retry check: option %s NOT yet selected — proceeding with retry click", letter)
        dispatched_letter = self._click_option_best_target(letter)
        self._last_dispatched_click_letter = dispatched_letter
        time.sleep(1.0)
        verified = self._verify_option_click(dispatched_letter)
        if verified:
            logger.info("Retry click verified for option %s (dispatched=%s)", letter, dispatched_letter)
            return

        logger.error("Click verification FAILED after retry for option %s", letter)
        self._sm.force_error(f"Input verification failed for option {letter}")
        self._alerts.raise_alert(
            AlertType.VERIFICATION_FAILURE,
            f"Click verification failed for option {letter} after retry",
        )

    def _candidate_option_click_sequence(self, intended_letter: str) -> list[str]:
        """
        Build deterministic fallback click targets around intended option.

        If option-row labeling drifts by +/-1 in a specific frame, this lets
        us correct it using verification feedback without blindly proceeding.
        """
        target = intended_letter.strip().upper()
        if target not in {"A", "B", "C", "D", "E"}:
            return [target]

        labels: list[str] = []
        try:
            if self._latest_interaction_ocr_layout is not None:
                option_map = self._latest_interaction_ocr_layout.get_option_map()
                if option_map is not None and option_map.options:
                    labels = [opt.label for opt in sorted(option_map.options, key=lambda o: o.circle_y)]
        except Exception:
            labels = []

        if not labels:
            labels = ["A", "B", "C", "D", "E"]
        labels = [l for l in labels if l in {"A", "B", "C", "D", "E"}]
        if target not in labels:
            labels.append(target)

        idx = labels.index(target)
        sequence: list[str] = [target]
        # Prefer nearest neighbors first.
        for d in (1, -1, 2, -2, 3, -3, 4, -4):
            j = idx + d
            if 0 <= j < len(labels):
                cand = labels[j]
                if cand not in sequence:
                    sequence.append(cand)
        # Keep attempts bounded for runtime predictability.
        return sequence[:4]

    def _click_option_best_target(self, letter: str) -> str:
        """
        Click an option using precise local-AI target when available,
        otherwise fallback to calibrated static option mapping.
        """
        target_letter = letter.strip().upper()
        if OCR_LAYOUT_PRIMARY_ENABLED and self._latest_interaction_ocr_layout is not None:
            resolved = self._latest_interaction_ocr_layout.locate_option_target_by_content(
                self._current_answer_text_for_click,
                target_letter,
            )
            if resolved is not None:
                resolved_letter, ocr_target = resolved
                if resolved_letter != target_letter:
                    logger.info(
                        "Content-locked remap on live frame: intended %s -> %s",
                        target_letter,
                        resolved_letter,
                    )
                logger.info("Using OCR-derived content-locked target for option %s", resolved_letter)
                self._last_option_click_target_norm = (float(ocr_target[0]), float(ocr_target[1]))
                self._click.click_at_normalized(
                    ocr_target[0],
                    ocr_target[1],
                    command=f"CLICK_{resolved_letter}",
                )
                return resolved_letter

            ocr_target = self._latest_interaction_ocr_layout.locate_option_target(target_letter)
            if ocr_target is not None:
                logger.info("Using OCR-derived target for option %s", target_letter)
                self._last_option_click_target_norm = (float(ocr_target[0]), float(ocr_target[1]))
                #region agent log
                from controller.utils.debug_ndjson import dbg as _dbg
                _dbg(
                    location="controller/orchestrator/workflow_engine.py:_click_option_best_target",
                    message="click option via OCRLayoutResult",
                    data={"letter": target_letter, "norm_x": float(ocr_target[0]), "norm_y": float(ocr_target[1])},
                    hypothesisId="H3",
                )
                #endregion agent log
                self._click.click_at_normalized(
                    ocr_target[0],
                    ocr_target[1],
                    command=f"CLICK_{target_letter}",
                )
                return target_letter
        if LOCAL_AI_ASSIST_ENABLED and self._latest_preprocessed_image_path is not None:
            target = locate_option_target(self._latest_preprocessed_image_path, target_letter)
            if target is not None:
                self._last_option_click_target_norm = (float(target[0]), float(target[1]))
                #region agent log
                from controller.utils.debug_ndjson import dbg as _dbg
                _dbg(
                    location="controller/orchestrator/workflow_engine.py:_click_option_best_target",
                    message="click option via local_ai locate_option_target",
                    data={"letter": target_letter, "norm_x": float(target[0]), "norm_y": float(target[1])},
                    hypothesisId="H3",
                )
                #endregion agent log
                self._click.click_at_normalized(target[0], target[1], command=f"CLICK_{target_letter}")
                return target_letter
        #region agent log
        from controller.utils.debug_ndjson import dbg as _dbg
        _dbg(
            location="controller/orchestrator/workflow_engine.py:_click_option_best_target",
            message="click option via calibrated fallback",
            data={"letter": target_letter},
            hypothesisId="H3",
        )
        #endregion agent log
        self._last_option_click_target_norm = None
        self._click.click_option(target_letter)
        return target_letter

    def _verify_option_click(self, letter: str) -> bool:
        """
        Verify whether an option click was registered.

        Uses Local AI (Qwen) if enabled, otherwise falls back
        to the CV-based verification engine.
        """
        self._verification_frame_event.clear()
        self._verification_frame_data = None
        self._is_waiting_verification_flag = True
        if self._request_capture_callback:
            self._request_capture_callback()
        arrived = self._verification_frame_event.wait(timeout=VERIFY_FRAME_TIMEOUT)
        self._is_waiting_verification_flag = False
        self._last_verification_timed_out = False
        if not arrived or self._verification_frame_data is None:
            logger.warning("Verification capture timed out after %ds", VERIFY_FRAME_TIMEOUT)
            self._last_verification_timed_out = True
            return False

        verify_path = self._receiver.receive_image(self._verification_frame_data)
        if LOCAL_AI_ASSIST_ENABLED:
            verify_preprocessed_path = self._preprocessor.preprocess(verify_path)
            verified, selected = check_is_answered(verify_preprocessed_path)
            if not verified:
                return False
            if selected is None:
                return False
            return selected.strip().upper() == letter.strip().upper()

        # Prefer verification around the exact OCR/local click target used.
        if self._last_option_click_target_norm is not None:
            nx, ny = self._last_option_click_target_norm
            exact = self._verify.verify_click_at_normalized_on_image(letter, verify_path, nx, ny)
            if exact.verified:
                return True

        # Local AI assist disabled: still verify against a dedicated fresh frame,
        # never reuse the pre-click screenshot path.
        return self._verify.verify_click_on_image(letter, verify_path).verified

    def _refresh_interaction_targets_post_ai(self) -> None:
        """
        Refresh click-target mapping from a dedicated post-AI capture.

        The stitched image is only used for question solving/context building.
        Live click coordinates are rebuilt from this fresh frame.
        """
        if self._sm.state != SystemState.RUNNING:
            logger.info("Skipping post-AI mapping capture — state is %s", self._sm.state.value)
            return
        self._mapping_frame_event.clear()
        self._mapping_frame_data = None
        self._is_waiting_mapping_flag = True
        if self._request_capture_callback:
            self._request_capture_callback()
        if self._sm.state != SystemState.RUNNING:
            self._is_waiting_mapping_flag = False
            return
        arrived = self._mapping_frame_event.wait(timeout=VERIFY_FRAME_TIMEOUT)
        self._is_waiting_mapping_flag = False
        if not arrived or self._mapping_frame_data is None:
            logger.warning(
                "Post-AI mapping capture timed out after %ds; using existing interaction targets",
                VERIFY_FRAME_TIMEOUT,
            )
            return

        mapping_path = self._receiver.receive_image(self._mapping_frame_data)
        mapping_preprocessed = self._preprocessor.preprocess(mapping_path)
        self._latest_preprocessed_image_path = mapping_preprocessed
        if OCR_LAYOUT_PRIMARY_ENABLED:
            self._latest_interaction_ocr_layout = self._ocr.analyze(mapping_preprocessed)

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
            if self._sm.state != SystemState.RUNNING:
                logger.info("Stopping scroll capture loop — state is %s", self._sm.state.value)
                break
            logger.info("Scroll frame %d/%d — scrolling %s", i + 1, MAX_SCROLL_FRAMES, direction)

            # Send scroll command.
            # Critical: "down" must NOT degrade to SCROLL_LEFT (sidebar click).
            dir_norm = (direction or "").strip().lower()
            if dir_norm == "right":
                self._click.scroll_right()
            elif dir_norm == "left":
                self._click.scroll_left()
            else:
                # Default vertical-scroll target: question panel center-left.
                # Use OCR/exam layout target when available for stable behavior.
                sx, sy = (0.33, 0.60)
                if OCR_LAYOUT_PRIMARY_ENABLED and self._latest_ocr_layout is not None and self._latest_ocr_layout.layout is not None:
                    qp = self._latest_ocr_layout.layout.question_panel
                    if qp is not None:
                        sx = max(0.0, min(1.0, float(qp.x + int(qp.w * 0.6)) / float(max(1, self._latest_ocr_layout.image_w - 1))))
                        sy = max(0.0, min(1.0, float(qp.y + int(qp.h * 0.6)) / float(max(1, self._latest_ocr_layout.image_h - 1))))
                #region agent log
                from controller.utils.debug_ndjson import dbg as _dbg
                _dbg(
                    location="controller/orchestrator/workflow_engine.py:_capture_scroll_frames",
                    message="vertical scroll dispatch",
                    data={"direction": dir_norm or "down", "norm_x": float(sx), "norm_y": float(sy)},
                    hypothesisId="H5",
                )
                #endregion agent log
                self._click.scroll_down_at_normalized(sx, sy)

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

            # Check if more scrolling is needed (local AI first if enabled)
            if LOCAL_AI_ASSIST_ENABLED:
                still_needs_scroll = check_needs_scroll(self._preprocessor.preprocess(frame_path))
            else:
                scroll_result = self._scroll_detector.detect(frame_path)
                still_needs_scroll = scroll_result.needs_scroll
            if not still_needs_scroll:
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
                "E": response.options.E,
            },
            "answer": response.answer,
            "answer_content": response.answer_content,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.debug("AI response saved: %s", path)

    def _compute_expected_option_count(
        self,
        ai_response: Optional[GrokResponse],
        cached_question: Optional[dict],
    ) -> Optional[int]:
        """Determine expected option count from AI response or cached question.

        Returns 4 if option E is empty/absent, 5 if present, or None if
        the count cannot be determined.
        """
        # Priority 1: AI response options
        if ai_response is not None:
            try:
                opt_e = (ai_response.options.E or "").strip()
                if not opt_e:
                    logger.info("AI response has empty option E — expecting 4 options")
                    return 4
                return 5
            except Exception:
                pass

        # Priority 2: Cached question record
        if cached_question is not None:
            opt_e = (cached_question.get("option_e", "") or "").strip()
            if not opt_e:
                logger.info("Cached question has empty option_e — expecting 4 options")
                return 4
            return 5

        return None

    def _validate_cache_hit(self, cached: dict) -> bool:
        """Validate an image-hash cache hit against live on-screen content.

        Prevents false identity reuse when two different questions hash
        similarly (adjacent questions with matching layouts).

        Checks:
            1. Same-question-id guard: if we just answered this exact
               question_id, it's likely a genuine same-screen (NEXT failed).
            2. Option text overlap: at least one stored option must
               fuzzy-match a detected on-screen option.

        Returns True if the match is sufficiently confirmed, False if
        the cache hit should be rejected.
        """
        cached_qid = cached.get("question_id")

        # Guard 1: If this is the exact question we just answered,
        # the screen genuinely hasn't changed — trust the hit.
        # BUT: if we just successfully navigated (_expecting_next_change),
        # we're guaranteed on a different question. A pHash collision
        # to the same question_id must NOT be auto-trusted; fall through
        # to Guard 2 (option text overlap) for real validation.
        if (
            cached_qid is not None
            and cached_qid == self._last_answered_question_id
            and not self._expecting_next_change
        ):
            logger.info(
                "Cache hit validated: same question_id=%d as last answered",
                cached_qid,
            )
            return True

        # Guard 2: Option text overlap.
        # Compare stored option texts against live OCR-detected options.
        # This catches the case where two different questions hash similarly
        # but have completely different option content.
        if self._latest_ocr_layout is not None:
            option_map = self._latest_ocr_layout.get_option_map()
            if option_map is not None and hasattr(option_map, "options") and option_map.options:
                from controller.utils.text_normalizer import normalize_for_matching

                stored_opts = [
                    cached.get("option_a", ""),
                    cached.get("option_b", ""),
                    cached.get("option_c", ""),
                    cached.get("option_d", ""),
                    cached.get("option_e", ""),
                ]
                stored_norm = {
                    normalize_for_matching(o) for o in stored_opts if o.strip()
                }

                detected_norm = set()
                for opt in option_map.options:
                    txt = getattr(opt, "text", "") or ""
                    if txt.strip():
                        detected_norm.add(normalize_for_matching(txt))

                if stored_norm and detected_norm:
                    # Check if any stored option is a substring of (or equals)
                    # any detected option, or vice versa. This handles partial
                    # OCR reads (e.g., OCR reads "23.5" from "Rs. 23.5 crore").
                    overlap = False
                    for s in stored_norm:
                        if not s:
                            continue
                        for d in detected_norm:
                            if not d:
                                continue
                            # Exact match or significant substring overlap
                            if s == d or (len(s) >= 4 and s in d) or (len(d) >= 4 and d in s):
                                overlap = True
                                break
                        if overlap:
                            break

                    if not overlap:
                        logger.warning(
                            "Cache hit validation FAILED: zero option text overlap "
                            "(stored=%r, detected=%r)",
                            stored_norm,
                            detected_norm,
                        )
                        return False
                    logger.info("Cache hit validated: option text overlap confirmed")
                else:
                    # Not enough data to validate — trust the hash
                    logger.debug("Cache hit validation: insufficient option data, trusting hash")
            else:
                # No option map available — trust the hash
                logger.debug("Cache hit validation: no option map available, trusting hash")
        else:
            # No OCR layout — trust the hash
            logger.debug("Cache hit validation: no OCR layout available, trusting hash")

        return True

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

    def _query_primary_with_fallback(self, stitched_path: Path) -> tuple[GrokResponse, str, str]:
        """
        Query selected cloud provider first, then fallback once to the other
        provider if available and primary fails.
        """
        if self._ai_provider == "gemini":
            primary = ("gemini", GEMINI_MODEL, query_gemini, bool(GEMINI_API_KEY))
            secondary = ("grok", GROK_MODEL, query_grok, bool(GROK_API_KEY))
        else:
            primary = ("grok", GROK_MODEL, query_grok, bool(GROK_API_KEY))
            secondary = ("gemini", GEMINI_MODEL, query_gemini, bool(GEMINI_API_KEY))

        provider_name, model_name, query_fn, enabled = primary
        if not enabled:
            raise ParseError(f"Primary AI provider '{provider_name}' is not configured")
        try:
            logger.info("Querying cloud %s AI (%s)", provider_name.capitalize(), model_name)
            return query_fn(stitched_path), model_name, provider_name
        except (GrokAPIError, GeminiAPIError, ParseError) as primary_error:
            logger.warning("Primary provider '%s' failed: %s", provider_name, primary_error)
            fallback_name, fallback_model, fallback_fn, fallback_enabled = secondary
            if not fallback_enabled:
                raise primary_error
            logger.info("Falling back to cloud %s AI (%s)", fallback_name.capitalize(), fallback_model)
            return fallback_fn(stitched_path), fallback_model, fallback_name

    def _remap_letter_by_option_content(self, db_answer_text: str, fallback_letter: str) -> str:
        """
        Map DB/AI answer text to current on-screen option content.
        This keeps clicks correct when options are shuffled.
        """
        try:
            # Prefer the latest interaction frame map so letter mapping and click
            # targeting use the same live on-screen source of truth.
            layout_source = self._latest_interaction_ocr_layout or self._latest_ocr_layout
            if layout_source is None:
                return fallback_letter
            option_map = layout_source.get_option_map()
            if option_map is None or not option_map.options:
                return fallback_letter
            current_options = {opt.label: (opt.text or "") for opt in option_map.options}
            match = match_option_by_content(db_answer_text or "", current_options)
            if match.found and match.matched_letter:
                logger.info(
                    "Remapped answer by on-screen content: %s -> %s (confidence=%s)",
                    fallback_letter,
                    match.matched_letter,
                    match.confidence,
                )
                return match.matched_letter
            return fallback_letter
        except Exception:
            return fallback_letter

    def _question_panel_text_truncated(self, ocr_res: OCRLayoutResult) -> bool:
        """
        Heuristic: if OCR words in question panel touch near the bottom edge,
        treat as truncated content requiring scroll.
        """
        try:
            if ocr_res is None or ocr_res.layout is None or ocr_res.layout.question_panel is None:
                return False
            qp = ocr_res.layout.question_panel
            panel_h = max(1, qp.h)
            bottom_band_y = qp.y + int(panel_h * 0.93)
            words = [
                w for w in ocr_res.words
                if qp.x <= w.cx <= qp.x2 and qp.y <= w.cy <= qp.y2
            ]
            if len(words) < 10:
                return False
            near_bottom = [w for w in words if w.cy >= bottom_band_y]
            return len(near_bottom) >= 2
        except Exception:
            return False

    def _try_db_decision_from_ocr(self) -> Optional[AnswerDecision]:
        """
        Attempt a DB-only decision using OCR-extracted question/options.
        This runs before cloud AI to reduce unnecessary API calls.
        """
        try:
            if self._latest_ocr_layout is None or self._latest_ocr_layout.layout is None:
                return None
            layout = self._latest_ocr_layout.layout
            q_panel = layout.question_panel
            if q_panel is None:
                return None

            # Build question text from OCR words inside question panel.
            q_words = [
                w for w in self._latest_ocr_layout.words
                if q_panel.x <= w.cx <= q_panel.x2 and q_panel.y <= w.cy <= q_panel.y2
            ]
            if len(q_words) < 8:
                return None
            q_words_sorted = sorted(q_words, key=lambda w: (w.y, w.x))
            question_text = " ".join(w.text for w in q_words_sorted).strip()
            if len(question_text) < 40:
                return None

            option_map = self._latest_ocr_layout.get_option_map()
            if option_map is None or not option_map.options:
                return None
            current_options = {opt.label: (opt.text or "") for opt in option_map.options}
            non_empty = sum(1 for t in current_options.values() if (t or "").strip())
            if non_empty < 2:
                return None

            match = match_question(
                db=self._db,
                test_id=self._test_id,
                question_text=question_text,
                options=current_options,
            )
            if not match.is_cached or not match.question_record:
                return None

            db_answer = match.correct_answer or ""
            option_match = match_option_by_content(db_answer, current_options)
            if not option_match.found or not option_match.matched_letter:
                return None

            logger.info(
                "OCR DB pre-check HIT: question_id=%d source=%s mapped=%s",
                match.question_record["question_id"],
                match.source.value,
                option_match.matched_letter,
            )
            return AnswerDecision(
                outcome=DecisionOutcome.CLICK,
                click_letter=option_match.matched_letter,
                source=f"database_ocr_{match.source.value}",
                question_id=match.question_record["question_id"],
                match_result=match,
            )
        except Exception:
            return None

    def _is_exam_screen_despite_low_density(self, image_path: Path, validation) -> bool:
        """
        Allow valid exam screens that fail cosmetic heuristics (low density,
        high uniformity, etc.) as long as the structural exam layout and
        at least 3 radio-button options are clearly detectable.
        """
        try:
            issues = list(getattr(validation, "issues", []) or [])
            if not issues:
                return False
            # Accept failures that are purely cosmetic false-positives on
            # real exam screens: low density, limited content zones,
            # and high uniformity (large white answer panel).
            benign_keywords = (
                "Very low text/content density",
                "Content in only",
                "uniform",
            )
            cosmetic_only = all(
                any(kw.lower() in str(i).lower() for kw in benign_keywords)
                for i in issues
            )
            if not cosmetic_only:
                return False
            layout = ExamLayoutDetector().detect(image_path)
            if layout is None or layout.answer_panel is None:
                return False
            option_map = OptionDetector().detect(image_path, layout)
            return option_map.count >= 3
        except Exception:
            return False
