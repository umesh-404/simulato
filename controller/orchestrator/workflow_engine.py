"""
Workflow engine.

Implements the main question-processing loop described in
Architecture Spec Section 17:

    1. Capture screenshot
    2. Validate screen (fail-safe)
    3. Detect scrolling requirement
    4. Capture additional frames if needed
    5. Stitch frames into composite image
    6. Send to Gemini AI
    7. Parse response
    8. Build answer decision
    9. Dispatch click command
    10. Verify click
    11. Click NEXT
    12. Log everything

Each step is logged and artifacts are saved for replay (Canonical Law 2, 11).
"""

import json
import time
import threading
import concurrent.futures
from pathlib import Path
from typing import Optional

from controller.ai_pipeline.gemini_client import query_gemini, GeminiAPIError

from controller.ai_pipeline.response_parser import AIResponse, ParseError
from controller.config import (
    CAPTURE_MODE,
    OCR_LAYOUT_PRIMARY_ENABLED,
    GEMINI_MODEL,
    VERIFY_FRAME_TIMEOUT_SECONDS,
)

# Ghost mode uses drastically shorter sleeps because captures are
# instant (~50ms via DXGI+LAN) vs phone-camera mode (~2s shutter lag).
_GHOST = CAPTURE_MODE == "ghost"
from controller.answer_engine.decision_engine import (
    AnswerDecision,
    DecisionOutcome,
)

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
        alert_manager: AlertManager,
        click_dispatcher: ClickDispatcher,
        verification_engine: VerificationEngine,
        image_receiver: ImageReceiver,
        event_logger: EventLogger,
    ) -> None:
        self._sm = state_machine
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

        self._test_name: Optional[str] = None
        self._question_number = 0
        self._api_calls = 0
        self._expecting_next_change: bool = False
        self._no_change_after_next_count: int = 0
        self._last_raw_phash: str | None = None

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
        self._request_recalibration_callback: Optional[callable] = None

        self._last_verification_timed_out: bool = False
        self._last_option_click_target_norm: tuple[float, float] | None = None

        self._last_dispatched_click_letter: str | None = None
        # When a click fails verification due to large drift, we pause and
        # request recalibration.  This stores the letter we need to retry
        # once the system resumes after recalibration.
        self._pending_recalib_retry_letter: str | None = None


        # Background thread pool for speculative early AI calls.
        # A single worker ensures at most one speculative call in flight.
        self._ai_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="speculative_ai",
        )

    def set_capture_callback(self, callback) -> None:
        """Set callback to request capture from the phone."""
        self._request_capture_callback = callback

    def set_recalibration_callback(self, callback) -> None:
        """Set callback to request recalibration from the system controller."""
        self._request_recalibration_callback = callback



    @property
    def question_number(self) -> int:
        return self._question_number

    @property
    def api_calls(self) -> int:
        return self._api_calls



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
        self._test_name = test_name
        self._question_number = 0
        self._api_calls = 0
        self._expecting_next_change = False
        self._no_change_after_next_count = 0
        self._last_raw_phash = None
        self._latest_ocr_layout = None
        self._latest_interaction_ocr_layout = None
        self._latest_preprocessed_image_path = None
        self._last_dispatched_click_letter = None
        self._mapping_frame_data = None
        self._is_waiting_mapping_flag = False
        self._mapping_frame_event.set()
        logger.info("Test context set: %s", test_name)

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

        if self._test_name is None:
            logger.error("No test context set")
            return None

        # ---- Resume from recalibration pause ----
        # If we paused for recalibration and the operator has recalibrated +
        # pressed CONTINUE, retry the failed click using the newly calibrated
        # grid_map positions.
        retry_letter = self._pending_recalib_retry_letter
        if retry_letter is not None:
            self._pending_recalib_retry_letter = None
            logger.info(
                "Resuming after recalibration — retrying click for option %s (question %d)",
                retry_letter, self._question_number,
            )
            # Use the calibrated grid_map position directly for the retry.
            # This bypasses live detection entirely, which may have been
            # picking up false positives (e.g. the Clear button).
            try:
                self._click.click_option(retry_letter)
                time.sleep(0.3 if _GHOST else 1.8)
                verified = self._verify_option_click(retry_letter)
                if verified:
                    logger.info("Post-recalibration click verified for option %s", retry_letter)
                else:
                    logger.warning(
                        "Post-recalibration click for %s not verified — proceeding anyway",
                        retry_letter,
                    )
            except Exception as e:
                logger.warning("Post-recalibration click retry failed: %s", e)
            # Advance to next question (snapshot was already stored before pause).
            self.advance_to_next()
            return None

        if not _GHOST:
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
                "test_name": self._test_name,
                "ocr_enabled": bool(OCR_LAYOUT_PRIMARY_ENABLED),

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
                same_screen = hamming <= 3
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

            # --- Speculative early AI call ---
            # Fire the AI query with the raw image BEFORE preprocessing/OCR.
            # The AI response will already be waiting by the time local
            # processing completes, eliminating the blocking API wait.
            speculative_future: Optional[concurrent.futures.Future] = None
            try:
                speculative_future = self._ai_executor.submit(
                    self._speculative_ai_query, image_path,
                )
                logger.info("Speculative AI call launched with raw image")
            except Exception as e:
                logger.warning("Failed to launch speculative AI call: %s", e)

            # Step 3: Preprocess the single captured frame.
            # No scroll detection or stitching — the exam UI fits in one frame.
            preprocessed_path = self._preprocessor.preprocess(image_path)
            self._latest_preprocessed_image_path = preprocessed_path
            is_stitched = False

            # Step 4: Layout detection + option detection.
            # Runs layout detect → HoughCircles option detect in one pass.
            # Pytesseract OCR runs as fallback only if option detection
            # finds fewer than 3 options.
            if OCR_LAYOUT_PRIMARY_ENABLED:
                self._latest_ocr_layout = self._ocr.analyze(preprocessed_path)
                self._latest_interaction_ocr_layout = self._latest_ocr_layout
            else:
                self._latest_ocr_layout = None
                self._latest_interaction_ocr_layout = None

            # (Duplicate increment removed. In ghost mode, question sequence is irrelevant.)
            if not _GHOST:
                logger.info("Question number: %d (auto-increment skipped in ghost mode)", self._question_number)

            ai_response = None
            ai_model_used = ""

            # Step 5: Query AI
            # The speculative call was launched immediately after screen validation
            # (before preprocessing), so it's been running in parallel.
            SPECULATIVE_WAIT = 65  # seconds — covers Gemini non-reasoning 2-retry cycle
            if speculative_future is not None:
                try:
                    spec_response, spec_model = speculative_future.result(
                        timeout=SPECULATIVE_WAIT,
                    )
                    ai_response = spec_response
                    ai_model_used = spec_model
                    self._api_calls += 1
                    logger.info(
                        "Using speculative AI result (model=%s, answer=%s)",
                        spec_model, ai_response.answer,
                    )
                    self._log_event("ai_response", {
                        "model": ai_model_used,
                        "answer": ai_response.answer,
                        "speculative": True,
                    })
                except Exception as spec_err:
                    logger.warning(
                        "Speculative AI call did not complete in time (%s) — falling back to standard call",
                        spec_err,
                    )
                    ai_response = None

            # Standard AI call: fallback when speculative failed/timed out.
            if ai_response is None:
                try:
                    ai_response, ai_model_used = self._query_gemini(image_path, is_stitched=False)
                    self._api_calls += 1
                    self._log_event("ai_response", {
                        "model": ai_model_used,
                        "answer": ai_response.answer,
                        "speculative": False,
                    })
                except (GeminiAPIError, ParseError) as e:
                    self._sm.force_error(f"AI processing failed: {e}")
                    self._alerts.raise_alert(
                        AlertType.AI_PARSE_FAILURE,
                        f"AI processing failed: {e}",
                    )
                    self._log_event("ai_error", {"error": str(e)})
                    return None

            # Step 6: Build decision directly from AI response.
            logger.info("Using AI answer directly: %s", ai_response.answer if ai_response else "None")
            decision = AnswerDecision(
                outcome=DecisionOutcome.CLICK,
                click_letter=ai_response.answer if ai_response is not None else None,
                source="ai_direct",
            )

            # Step 7: Handle outcome
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

            if decision.click_letter:
                self._log_event("answer_decision", {
                    "question_number": self._question_number,
                    "click_letter": decision.click_letter,
                    "dispatched_letter": self._last_dispatched_click_letter,
                    "source": decision.source,
                })

            return decision

    def advance_to_next(self) -> None:
        """
        Click NEXT to advance to the next question.
        Follows Hardware Input Transaction flow (Canonical Law 5):
        send click → wait for navigation → verify screen changed → retry → alert.

        Last-question guard: if the footer shows only "Prev" (no "Next"),
        the exam has reached the last question. The system raises an alert,
        sounds the alarm, and waits for manual intervention.
        """
        if self._sm.state != SystemState.RUNNING:
            return
        logger.info("Advancing to next question")

        # Capture a reference frame *before* clicking NEXT so we can
        # verify the screen actually changed afterwards.
        pre_next_path = self._capture_single_frame_for_ref()

        # --- Last-question guard ---
        # The ExamLayoutDetector parses the footer OCR during the initial
        # analyze() pass. If it found "Prev" but no "Next", it set is_last_question.
        if self._latest_ocr_layout and self._latest_ocr_layout.layout and self._latest_ocr_layout.layout.is_last_question:
            logger.info(
                "LAST QUESTION DETECTED — footer shows 'Prev' but no 'Next'. "
                "All questions answered. Raising alert and waiting for operator."
            )
            self._log_event("last_question_detected", {
                "question_number": self._question_number,
            })
            self._sm.force_error("All questions answered — last question reached")
            self._alerts.raise_alert(
                AlertType.TEST_COMPLETE,
                "All questions have been answered. The exam has reached the last question. "
                "Please review and submit manually.",
                data={"question_number": self._question_number},
            )
            return

        # Not the last question — proceed with NEXT click.
        self._click_next_best_target()
        self._log_event("click_next", {"after_question": self._question_number})

        # Browser needs time to process the click and navigate.
        time.sleep(0.5 if _GHOST else 2.5)

        result = self._verify_next_click_by_change(pre_next_path)
        if result.verified:
            logger.info("NEXT click verified (screen changed)")
            self._expecting_next_change = True
            self._no_change_after_next_count = 0
            return

        # Passive re-check: wait a bit and compare again.
        logger.warning("NEXT click verification borderline — passive re-check")
        time.sleep(0.3 if _GHOST else 1.5)
        recheck = self._verify_next_click_by_change(pre_next_path)
        if recheck.verified:
            logger.info("NEXT re-check verified (screen changed)")
            self._expecting_next_change = True
            self._no_change_after_next_count = 0
            return

        # Re-check confirmed the screen did NOT change — the click missed.
        # Retry the NEXT click once. This is safe because we've verified
        # that we're still on the same screen (the option is still selected).
        logger.warning("NEXT click missed (re-check confirmed no change) — retrying NEXT click")
        self._click_next_best_target()
        time.sleep(0.5 if _GHOST else 2.5)
        retry_result = self._verify_next_click_by_change(pre_next_path)
        if retry_result.verified:
            logger.info("NEXT retry click verified (screen changed)")
            self._expecting_next_change = True
            self._no_change_after_next_count = 0
            return

        # Even the retry failed. Let the pHash guard handle it on the
        # next cycle — but reset the counter so the first observation
        # of same-screen doesn't immediately trigger TEST_COMPLETE.
        logger.warning(
            "NEXT retry also inconclusive — proceeding. "
            "Next cycle pHash guard will catch true failures."
        )
        self._expecting_next_change = True
        self._no_change_after_next_count = 0

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

            pre_hash = self._compute_image_phash(pre_next_path)
            post_hash = self._compute_image_phash(post_path)
            hamming = 0
            if pre_hash and post_hash:
                hamming = sum(a != b for a, b in zip(pre_hash, post_hash))

            if q_diff is not None:
                logger.info(
                    "NEXT verify: question_panel_diff=%.1f, full_diff=%.1f",
                    q_diff, full_mean,
                )
            else:
                logger.info("NEXT verify: full_diff=%.1f (no q-panel region)", full_mean)
            logger.info("NEXT verify: pHash hamming distance=%d", hamming)

            # --- Tier 1: strong single-signal evidence ---
            # Camera noise between captures of the *same* screen: q_panel 2-3,
            # full 2-4, pHash 0-3.  Real navigation: q_panel 5+, full 5+,
            # pHash 6+.  The borderline zone (q_panel 3.5-5, pHash 4-7) is
            # where false negatives cause destructive NEXT retries that skip
            # questions — a far worse outcome than a false positive (which is
            # caught by the pHash same-screen guard on the next cycle).
            if q_diff is not None and q_diff > 4.5:
                return VerificationResult(
                    verified=True,
                    details="question_panel_changed",
                    confidence=min(q_diff / 20.0, 1.0),
                )
            if full_mean > 5.5:
                logger.info("NEXT verified: full mean pixel diff = %.1f", full_mean)
                return VerificationResult(
                    verified=True,
                    details="screen_changed",
                    confidence=min(full_mean / 15.0, 1.0),
                )
            if hamming >= 6:
                return VerificationResult(
                    verified=True,
                    details="phash_changed",
                    confidence=min(hamming / 32.0, 1.0),
                )

            # --- Tier 2: combined weak signals ---
            # When no single metric crosses its threshold, a combination of
            # moderate signals still indicates a real change.
            combined = (
                (q_diff is not None and q_diff > 3.5)
                and (hamming >= 4)
            )
            if combined:
                logger.info(
                    "NEXT verified via combined signals (q_panel=%.1f + hamming=%d)",
                    q_diff, hamming,
                )
                return VerificationResult(
                    verified=True,
                    details="combined_signal_changed",
                    confidence=min((q_diff or 0) / 20.0 + hamming / 32.0, 1.0),
                )

            # --- Tier 3: pHash-only moderate signal ---
            # hamming=4 is above camera noise (0-3) and indicates content
            # change.  False positives here are harmless: the pHash
            # same-screen guard in the next process_question cycle catches
            # them.  False negatives (skipping questions via destructive
            # NEXT retry) are catastrophic and must be avoided.
            if hamming >= 4:
                logger.info(
                    "NEXT verified via pHash-only moderate signal (hamming=%d)",
                    hamming,
                )
                return VerificationResult(
                    verified=True,
                    details="phash_moderate_changed",
                    confidence=min(hamming / 32.0, 1.0),
                )

            logger.warning(
                "NEXT verification: screen did NOT change (full=%.1f, q_panel=%s, hamming=%d)",
                full_mean,
                f"{q_diff:.1f}" if q_diff is not None else "N/A",
                hamming,
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
        """Click NEXT using the calibrated grid-map position.

        The NEXT button is in the exam footer bar, which is darker than the
        main content area.  The screen-boundary transform (used for option
        radio buttons) only covers the bright content area and maps footer
        positions to below the screen.  Using the calibrated pixel position
        from grid_map (which applies a proportional fallback for footer
        elements) avoids this problem entirely.
        """
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
        time.sleep(0.3 if _GHOST else 2.2)
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
        time.sleep(0.2 if _GHOST else 1.0)
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

        # Tripod-mounted capture: coordinates are stable, no need to
        # re-detect options. The same click target is used for retry.

        dispatched_letter = self._click_option_best_target(letter)
        self._last_dispatched_click_letter = dispatched_letter
        time.sleep(0.3 if _GHOST else 2.2)
        verified = self._verify_option_click(dispatched_letter)
        if verified:
            logger.info("Retry click verified for option %s (dispatched=%s)", letter, dispatched_letter)
            return

        logger.error("Click verification FAILED after retry for option %s", letter)

        # ---------------------------------------------------------------
        # Auto-recalibration recovery (Canonical Law 5 extension):
        #
        # When click verification fails after standard retry, the most
        # common root cause is a stale/inaccurate calibration grid_map
        # (e.g. bad option detection during calibration produced wrong
        # estimated positions for D/E).
        #
        # Instead of immediately going to ERROR, we:
        #   1. Capture a fresh frame  (the current exam screen)
        #   2. Run calibrate_from_screenshot on it
        #   3. Save the new grid_map if successful
        #   4. Re-detect options and retry the click
        #   5. If still failing after recalibration → then error out
        # ---------------------------------------------------------------
        logger.info(
            "Attempting auto-recalibration recovery for option %s",
            letter,
        )

        recalib_success = False
        try:
            from calibration.coordinate_solver import calibrate_from_screenshot
            from calibration.grid_mapper import GridMap

            # Request a fresh capture for recalibration.
            self._verification_frame_event.clear()
            self._verification_frame_data = None
            self._is_waiting_verification_flag = True
            if self._request_capture_callback:
                self._request_capture_callback()
            arrived = self._verification_frame_event.wait(timeout=VERIFY_FRAME_TIMEOUT)
            self._is_waiting_verification_flag = False

            if arrived and self._verification_frame_data is not None:
                # Save recalibration image to the calibration directory.
                from datetime import datetime, timezone
                cal_dir = Path("runs") / "calibration"
                cal_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                recalib_path = cal_dir / f"calibration_auto_{ts}.jpg"
                recalib_path.write_bytes(self._verification_frame_data)
                logger.info(
                    "Auto-recalibration: saved frame as %s (%d bytes)",
                    recalib_path.name, len(self._verification_frame_data),
                )

                result = calibrate_from_screenshot(recalib_path)
                if result.success and result.grid_map is not None:
                    result.grid_map.save()
                    recalib_success = True
                    logger.info(
                        "Auto-recalibration SUCCEEDED: %d positions mapped",
                        len(result.grid_map.positions),
                    )

                    # Best-effort: update header anchor template.
                    try:
                        from controller.capture_pipeline.header_anchor import HeaderAnchor
                        HeaderAnchor.ensure_template_from_image(recalib_path, force=True)
                    except Exception:
                        pass
                else:
                    logger.warning(
                        "Auto-recalibration FAILED: %s",
                        result.message if result else "no result",
                    )
            else:
                logger.warning("Auto-recalibration: capture timed out (no frame received)")

        except Exception as e:
            logger.warning("Auto-recalibration failed with exception: %s", e)

        if recalib_success:
            # Re-detect options on the latest frame with fresh calibration.
            try:
                latest_img = self._latest_preprocessed_image_path
                if latest_img is not None:
                    fresh_ocr = OCRLayoutAnalyzer().analyze(latest_img)
                    if fresh_ocr is not None:
                        self._latest_interaction_ocr_layout = fresh_ocr
                        logger.info("Refreshed option targets after auto-recalibration")
            except Exception as e:
                logger.warning("Post-recalibration option refresh failed: %s", e)

            # Final retry with fresh calibration
            logger.info("Post-recalibration retry click for option %s", letter)
            dispatched_letter = self._click_option_best_target(letter)
            self._last_dispatched_click_letter = dispatched_letter
            time.sleep(0.3 if _GHOST else 2.2)
            verified = self._verify_option_click(dispatched_letter)
            if verified:
                logger.info(
                    "Post-recalibration click VERIFIED for option %s (dispatched=%s)",
                    letter, dispatched_letter,
                )
                return
            logger.error(
                "Post-recalibration click verification STILL FAILED for option %s",
                letter,
            )

        # All recovery attempts exhausted — this is a genuine failure.
        # Force ERROR state and alert the operator.
        self._sm.force_error(f"Input verification failed for option {letter}")
        self._alerts.raise_alert(
            AlertType.VERIFICATION_FAILURE,
            f"Click verification failed for option {letter} after auto-recalibration retry",
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

    def _log_screen_coords_for_click(self, letter: str, norm_x: float, norm_y: float) -> None:
        """Log the estimated screen-space pixel position for a click dispatch."""
        try:
            from calibration.grid_mapper import GridMap
            gm = GridMap.load()
            cap_w, cap_h = gm.capture_resolution
            px = int(round(norm_x * max(1, cap_w - 1)))
            py = int(round(norm_y * max(1, cap_h - 1)))
            sx, sy = gm.capture_to_screen_pixel(px, py)
            calib = gm.pixel_positions.get(letter)
            calib_str = f"calibrated=({calib[0]},{calib[1]})" if calib else "no calibration"
            logger.info(
                "Click %s screen-space: (%d,%d) from capture(%d,%d), %s",
                letter, sx, sy, px, py, calib_str,
            )
        except Exception:
            pass

    # Calibration blend thresholds.
    # The exam UI uses a responsive split-pane, so the radio-button column
    # (X-axis) and item rows (Y-axis) can shift dramatically between
    # questions when divider_x moves (observed: 2128 → 1642 = 486px shift
    # in capture space, ~230px in screen space).
    # Live detection from OptionDetector always reflects the CURRENT layout.
    # Calibration is only used as a tiny stabilizer when positions are close.
    _CALIB_BLEND_MAX_X_DELTA = 150   # beyond this, trust live X entirely
    _CALIB_BLEND_MAX_Y_DELTA = 200   # beyond this, trust live Y entirely

    def _blend_with_calibration(
        self,
        letter: str,
        live_norm: tuple[float, float],
    ) -> tuple[float, float]:
        """Blend live-detected capture-normalized coords with calibration.

        Live-detection-primary strategy:
        - ALWAYS prefer live detection (OptionDetector finds circles on the
          current frame, so it reflects the actual layout).
        - Calibration is only used as a small smoothing factor when the
          live detection is very close to calibration (within thresholds).
        - When the split-pane divider shifts, calibration X/Y can be
          hundreds of pixels off — we must NOT fall back to it.

        In ghost mode (CAPTURE_MODE=ghost), coordinates are pixel-perfect
        (identity transform) so blending is skipped entirely.
        """
        # Ghost mode: identity transform — live detection IS exact truth.
        from controller.config import CAPTURE_MODE
        if CAPTURE_MODE == "ghost":
            logger.info(
                "Ghost mode: using live detection for %s without blending "
                "(identity transform, ±0px accuracy)",
                letter,
            )
            return live_norm

        try:
            from calibration.grid_mapper import GridMap
            gm = GridMap.load()
            calib_pixel = gm.pixel_positions.get(letter.strip().upper())
            if calib_pixel is None:
                return live_norm

            cap_w, cap_h = gm.capture_resolution
            calib_sx, calib_sy = calib_pixel

            # Convert live norm -> capture pixel -> screen pixel
            live_cap_x = int(round(live_norm[0] * max(1, cap_w - 1)))
            live_cap_y = int(round(live_norm[1] * max(1, cap_h - 1)))
            live_sx, live_sy = gm.capture_to_screen_pixel(live_cap_x, live_cap_y)

            dx = abs(live_sx - calib_sx)
            dy = abs(live_sy - calib_sy)

            # --- X axis: prefer live detection ---
            if dx <= self._CALIB_BLEND_MAX_X_DELTA:
                # Small X delta: light blend to smooth HoughCircles jitter
                final_sx = live_sx * 0.8 + calib_sx * 0.2
                x_mode = "blend"
            else:
                # Large X delta: layout shifted (responsive UI), trust live
                final_sx = float(live_sx)
                x_mode = "live"

            # --- Y axis: prefer live detection ---
            if dy <= self._CALIB_BLEND_MAX_Y_DELTA:
                # Moderate Y delta: blend primarily with live
                final_sy = live_sy * 0.85 + calib_sy * 0.15
                y_mode = "live_primary"
            else:
                # Large Y delta: trust live completely (question length varies)
                final_sy = float(live_sy)
                y_mode = "live_large_shift"

            blend_mode = f"x={x_mode}, y={y_mode}"

            # Convert blended screen pixel back to capture-normalized.
            scale_x = float(gm.transform.get("scale_x", 1.0))
            scale_y = float(gm.transform.get("scale_y", 1.0))
            offset_x = float(gm.transform.get("offset_x", 0.0))
            offset_y = float(gm.transform.get("offset_y", 0.0))

            if scale_x == 0 or scale_y == 0:
                return live_norm

            blend_cap_x = (final_sx - offset_x) / scale_x
            blend_cap_y = (final_sy - offset_y) / scale_y

            blend_nx = max(0.0, min(1.0, blend_cap_x / max(1, cap_w - 1)))
            blend_ny = max(0.0, min(1.0, blend_cap_y / max(1, cap_h - 1)))

            logger.info(
                "Calibration blend for %s: live_screen=(%d,%d), calib=(%d,%d), "
                "final_screen=(%.0f,%.0f), delta=(%d,%d), mode=%s",
                letter, live_sx, live_sy, calib_sx, calib_sy,
                final_sx, final_sy, dx, dy, blend_mode,
            )
            return (blend_nx, blend_ny)

        except Exception as e:
            logger.debug("Calibration blend failed for %s: %s", letter, e)
            return live_norm

    def _click_option_best_target(self, letter: str) -> str:
        """
        Click an option using live detection, blended with calibration
        data for improved accuracy.

        OCR layout (primary) provides the live-detected radio circle
        position in capture-space.  When calibration data is available
        and close to the live detection, we blend the two (favouring
        calibration) to compensate for HoughCircles imprecision on
        phone-captured frames.
        """
        target_letter = letter.strip().upper()
        if OCR_LAYOUT_PRIMARY_ENABLED and self._latest_interaction_ocr_layout is not None:
            ocr_target = self._latest_interaction_ocr_layout.locate_option_target(target_letter)
            if ocr_target is not None:
                logger.info("Using OCR-derived target for option %s", target_letter)
                final_target = self._blend_with_calibration(target_letter, ocr_target)
                self._last_option_click_target_norm = (float(final_target[0]), float(final_target[1]))
                self._log_screen_coords_for_click(target_letter, float(final_target[0]), float(final_target[1]))
                #region agent log
                from controller.utils.debug_ndjson import dbg as _dbg
                _dbg(
                    location="controller/orchestrator/workflow_engine.py:_click_option_best_target",
                    message="click option via OCRLayoutResult",
                    data={"letter": target_letter, "norm_x": float(final_target[0]), "norm_y": float(final_target[1])},
                    hypothesisId="H3",
                )
                #endregion agent log
                self._click.click_at_normalized(
                    final_target[0],
                    final_target[1],
                    command=f"CLICK_{target_letter}",
                )
                return target_letter
        # ALL live detection methods failed — do NOT blindly use stale
        # calibration data.  Raise an error so the operator can intervene.
        logger.error(
            "All live detection methods failed for option %s — "
            "OCR content-lock and OCR label-based both returned None. "
            "Refusing to click from stale calibration data.",
            target_letter,
        )
        self._sm.force_error(
            f"Cannot locate option {target_letter} on live screen — "
            f"all detection methods exhausted"
        )
        self._alerts.raise_alert(
            AlertType.VERIFICATION_FAILURE,
            f"Could not detect option {target_letter} on screen. "
            f"Please verify exam screen is visible and retry.",
        )
        return target_letter

    def _verify_option_click(self, letter: str) -> bool:
        """
        Verify whether an option click was registered.

        Uses the CV-based verification engine.
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

        # Prefer verification around the exact OCR click target used.
        if self._last_option_click_target_norm is not None:
            nx, ny = self._last_option_click_target_norm
            exact = self._verify.verify_click_at_normalized_on_image(letter, verify_path, nx, ny)
            if exact.verified:
                return True

        # CV-based verification against a dedicated fresh frame.
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

            # Check if more scrolling is needed
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

    def _speculative_ai_query(
        self,
        raw_image_path: Path,
    ) -> tuple[AIResponse, str]:
        """Run the Gemini AI query speculatively in a background thread.

        Uses the raw captured image (before preprocessing/stitching) with
        no OCR context.  The vision model can still read the question and
        options directly from the raw screenshot.

        Returns:
            (AIResponse, model_name)

        Raises on any AI/parse error so that Future.result() surfaces it.
        """

        logger.info(
            "[Speculative] Querying Gemini (%s) with raw image",
            GEMINI_MODEL,
        )
        response = query_gemini(raw_image_path, ocr_context="", is_stitched=False)
        logger.info(
            "[Speculative] Gemini response received: answer=%s",
            response.answer,
        )
        return response, GEMINI_MODEL

    def _query_gemini(
        self,
        stitched_path: Path,
        is_stitched: bool = False,
    ) -> tuple[AIResponse, str]:
        """
        Query Gemini AI with the stitched/processed image.

        Returns:
            (AIResponse, model_name)

        Raises:
            GeminiAPIError: on HTTP-level failures.
            ParseError: on unparseable responses.
        """
        logger.info("Querying Gemini AI (%s)", GEMINI_MODEL)
        response = query_gemini(stitched_path, ocr_context="", is_stitched=is_stitched)
        return response, GEMINI_MODEL



    def _question_panel_text_truncated(self, ocr_res: OCRLayoutResult) -> bool:
        """
        Heuristic: if high-confidence OCR words in question panel touch near
        the bottom edge, treat as truncated content requiring scroll.

        Only words with confidence >= MIN_BOTTOM_CONF are counted.
        Diagonal watermark text (e.g. "23000003117") produces low-confidence
        OCR fragments that would otherwise trigger false scroll detection
        when they land near the panel bottom.

        Common navigation/status text (Marks, Negative, View More, Clear,
        Prev, Next) is filtered out to prevent false positives.
        """
        MIN_BOTTOM_CONF = 60
        # Navigation/status words that commonly appear near the question
        # panel bottom but do NOT indicate truncated content.
        STATUS_WORDS = {
            "marks", "negative", "view", "more", "clear",
            "prev", "next", "submit", "answered", "bookmarked",
            "skipped", "not", "viewed", "saved", "server",
            "section", "test",
        }
        try:
            if ocr_res is None or ocr_res.layout is None or ocr_res.layout.question_panel is None:
                return False
            qp = ocr_res.layout.question_panel
            panel_h = max(1, qp.h)
            # Bottom 5% of the question panel (tighter than 7%)
            bottom_band_y = qp.y + int(panel_h * 0.95)
            words = [
                w for w in ocr_res.words
                if qp.x <= w.cx <= qp.x2 and qp.y <= w.cy <= qp.y2
            ]
            if len(words) < 10:
                return False
            near_bottom = [
                w for w in words
                if (w.cy >= bottom_band_y
                    and w.conf >= MIN_BOTTOM_CONF
                    and w.text.strip().lower() not in STATUS_WORDS
                    and not w.text.strip().replace(".", "").replace(",", "").isdigit())
            ]
            if near_bottom:
                logger.debug(
                    "Truncation heuristic: %d high-conf words near bottom "
                    "(Y>=%d, conf>=%d): %s",
                    len(near_bottom), bottom_band_y, MIN_BOTTOM_CONF,
                    [(w.text, w.conf) for w in near_bottom[:5]],
                )
            return len(near_bottom) >= 3
        except Exception:
            return False


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
