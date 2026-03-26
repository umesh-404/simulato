"""
System controller — top-level orchestrator.

Wires all subsystems together and manages the lifecycle of
a Simulato test session.

Responsibilities:
    - Initialize all subsystems
    - Handle remote commands (CALIBRATE, START, PAUSE, STOP, STATUS)
    - Route captured images to the workflow engine
    - Manage operator decisions during alerts
    - Provide system status

The Main Control PC is the central orchestrator (Canonical Law 13).
"""

from pathlib import Path
from typing import Optional
import threading

from controller.alerts.alert_manager import AlertManager, AlertType, OperatorDecision
from controller.alerts.sound_player import play_alarm
from controller.capture_pipeline.image_receiver import ImageReceiver
from controller.hardware_control.click_dispatcher import ClickDispatcher
from controller.hardware_control.pi_client import PiClient, PiConnectionError, PiCommandError
from controller.hardware_control.verification_engine import VerificationEngine
from controller.mobile_api.api_server import queue_alert_for_broadcast
from controller.orchestrator.state_machine import StateMachine, SystemState, InvalidTransitionError
from controller.orchestrator.workflow_engine import WorkflowEngine
from controller.config import DEFAULT_AI_PROVIDER
from controller.replay.run_loader import create_run, RunContext
from controller.utils.logger import get_logger, EventLogger
from database.db_manager import DatabaseManager

logger = get_logger("system_controller")


class SystemController:
    """
    Top-level controller that manages the Simulato system lifecycle.
    """

    def __init__(self) -> None:
        self._sm = StateMachine()
        self._db = DatabaseManager()
        self._alert_mgr = AlertManager()
        self._pi_client = PiClient()
        self._click_dispatcher = ClickDispatcher(self._pi_client)
        self._verification_engine = VerificationEngine()

        self._alert_mgr.set_sound_callback(play_alarm)
        self._alert_mgr.set_notify_callback(queue_alert_for_broadcast)

        self._run_ctx: Optional[RunContext] = None
        self._workflow: Optional[WorkflowEngine] = None
        self._test_name: Optional[str] = None
        self._last_conflict_decision: Optional[dict] = None
        self._calibration_pending: bool = False
        self._state_before_calibration: Optional[SystemState] = None
        self._active_ai_provider: str = DEFAULT_AI_PROVIDER
        self._pending_start_payload: Optional[dict] = None
        self._pending_resume_after_calibration: bool = False
        self._timers: list[threading.Timer] = []
        self._timers_lock = threading.Lock()
        self._stream_frames_lock = threading.Lock()
        # Latest streamed JPEG bytes per device_id (in-memory only).
        self._latest_stream_frames: dict[str, bytes] = {}
        self._latest_stream_seq: dict[str, int | None] = {}
        # Primary-frame processing runs on a worker thread so verification/scroll
        # uploads can still be routed while a question is being processed.
        self._processing_lock = threading.Lock()
        self._processing_active: bool = False
        self._pending_primary_frame: Optional[tuple[bytes, str]] = None

    @property
    def state(self) -> SystemState:
        return self._sm.state

    @property
    def test_name(self) -> Optional[str]:
        return self._test_name

    @property
    def workflow(self) -> Optional[WorkflowEngine]:
        return self._workflow

    def get_status(self) -> dict:
        return {
            "system_state": self._sm.state.value,
            "active_test": self._test_name,
            "active_ai_provider": self._active_ai_provider,
            "question_number": self._workflow.question_number if self._workflow else 0,
            "api_calls": self._workflow.api_calls if self._workflow else 0,
            "cache_hits": self._workflow.cache_hits if self._workflow else 0,
            "image_hash_hits": self._workflow.image_hash_hits if self._workflow else 0,
        }

    # ------------------------------------------------------------------
    # Command handlers (from Remote Control Phone)
    # ------------------------------------------------------------------

    def handle_command(self, command: str, payload: Optional[dict] = None) -> dict:
        """
        Handle a remote command.

        Args:
            command: One of CALIBRATE, START, PAUSE, STOP, STATUS.
            payload: Optional additional data (e.g. test_name for START).

        Returns:
            Result dict.
        """
        command = command.upper()
        logger.info("Handling command: %s", command)

        # Allow operator recovery after STOP/ERROR without requiring app restart.
        # START/CALIBRATE/PAUSE/CONTINUE should deterministically revive the
        # controller back to IDLE first.
        if self._sm.state == SystemState.STOPPED and command in {"START", "CALIBRATE", "PAUSE"}:
            self._sm.transition_to(SystemState.IDLE, reason=f"recover_from_stopped:{command.lower()}")
            if command == "PAUSE":
                return {"status": "idle", "reason": "recovered_from_stopped"}
        if self._sm.state == SystemState.ERROR and command in {"START", "CALIBRATE", "PAUSE", "CONTINUE"}:
            self._sm.transition_to(SystemState.IDLE, reason=f"recover_from_error:{command.lower()}")
            if command in {"PAUSE", "CONTINUE"}:
                return {"status": "idle", "reason": "recovered_from_error"}

        handlers = {
            "CALIBRATE": self._handle_calibrate,
            "START": self._handle_start,
            "CONTINUE": self._handle_continue,
            "PAUSE": self._handle_pause,
            "STOP": self._handle_stop,
            "STATUS": self._handle_status,
            "SET_AI_PROVIDER": self._handle_set_ai_provider,
        }

        handler = handlers.get(command)
        if handler is None:
            logger.warning("Unknown command: %s", command)
            return {"error": f"Unknown command: {command}"}

        try:
            return handler(payload or {})
        except InvalidTransitionError as e:
            logger.error("Invalid state transition: %s", e)
            return {"error": str(e)}
        except (PiConnectionError, PiCommandError, ValueError) as e:
            logger.error("Command handling failed: %s", e)
            return {"error": str(e)}
        except Exception as e:
            logger.exception("Unhandled error while handling command %s", command)
            return {"error": f"Unhandled error: {e}"}

    def _handle_calibrate(self, payload: dict) -> dict:
        # Remember the state we are coming from so we can optionally resume
        self._state_before_calibration = self._sm.state
        self._sm.transition_to(SystemState.CALIBRATION, reason="operator_calibrate")
        logger.info("Calibration started — requesting capture from phone")

        # Set flag so next image received routes to calibration
        self._calibration_pending = True

        # Tell the capture phone to take a photo now via WebSocket
        import asyncio
        from controller.mobile_api import api_server
        if api_server._event_loop:
            asyncio.run_coroutine_threadsafe(
                api_server.registry.broadcast_to_role("capture", {
                    "type": "REMOTE_COMMAND",
                    "payload": {"command": "CAPTURE_IMAGE"}
                }),
                api_server._event_loop,
            )
        else:
            logger.warning("Event loop not available — capture phone must manually capture")

        return {"status": "calibration_started", "waiting_for": "capture"}

    def _handle_start(self, payload: dict) -> dict:
        # Require Pi connectivity for any run that will click answers.
        # If not connected, try reconnect once and block START with an alert.
        if not self._pi_client.is_connected():
            try:
                self._pi_client.connect()
            except PiConnectionError as e:
                self._alert_mgr.raise_alert(
                    AlertType.INPUT_FAILURE,
                    f"Pi not connected ({e}). Start the Pi listener and verify PI_HOST/PI_PORT.",
                )
                return {"error": f"Pi not connected: {e}"}

        test_name = (payload.get("test_name", "") or "").strip()
        if not test_name:
            # Provide a deterministic default context for mobile clients
            # that currently do not send test_name in START payload.
            test_name = "default_test"
            logger.warning("START received without test_name; using default_test")

        # Auto-calibrate on START if no valid grid_map.json exists.
        from calibration.grid_mapper import GridMap
        try:
            grid_map = GridMap.load()
        except Exception:
            logger.info("START requested but system not calibrated — starting calibration flow")
            self._pending_start_payload = {**(payload or {}), "test_name": test_name}
            # Start calibration immediately (one attempt). If it fails, operator can retry by pressing START again.
            self._alert_mgr.raise_alert(
                AlertType.CALIBRATION_REQUIRED,
                "Calibration required. Adjust the capture phone framing if needed, then press Retry Calibration.",
            )
            self._handle_calibrate({})
            return {"status": "calibrating", "waiting_for": "calibration"}

        self._test_name = test_name
        self._run_ctx = create_run(test_name)
        event_logger = EventLogger(self._run_ctx.run_dir)

        receiver = ImageReceiver(self._run_ctx.run_dir)

        # Wire verification engine to latest captured frame + calibrated grid,
        # so CV-based verification remains functional when local AI assist is disabled.
        self._verification_engine.set_grid_map(grid_map)
        self._verification_engine.set_capture_callback(
            lambda: receiver.latest_path
            if receiver.latest_path is not None
            else (self._run_ctx.run_dir / "screenshots" / "__missing__.jpg")
        )

        self._workflow = WorkflowEngine(
            state_machine=self._sm,
            db=self._db,
            alert_manager=self._alert_mgr,
            click_dispatcher=self._click_dispatcher,
            verification_engine=self._verification_engine,
            image_receiver=receiver,
            event_logger=event_logger,
        )
        self._workflow.set_test_context(test_name)
        self._workflow.set_capture_callback(self._request_capture)
        self._workflow.set_ai_provider(self._active_ai_provider)

        self._sm.transition_to(SystemState.RUNNING, reason=f"start_test:{test_name}")
        logger.info("Test started: %s (run: %s)", test_name, self._run_ctx.run_id)

        # Trigger the first capture to start the autonomous loop
        self._schedule_timer(1.0, self._request_capture)

        return {"status": "started", "run_id": self._run_ctx.run_id}

    def _handle_continue(self, payload: dict) -> dict:
        """
        Operator-confirmed continue after a manual intervention (typically recalibration).
        If a pending START exists (from auto-calibration on START), this starts the run.
        If a run already exists and we're PAUSED, this resumes and requests capture.
        """
        # Pending START path (auto-calibration then continue)
        if self._pending_start_payload is not None:
            pending = self._pending_start_payload
            self._pending_start_payload = None
            logger.info("CONTINUE received — starting pending run after calibration")
            return self._handle_start(pending)

        # Resume path
        if self._sm.state == SystemState.PAUSED:
            self._sm.transition_to(SystemState.RUNNING, reason="operator_continue")
            self._request_capture()
            return {"status": "resumed"}

        return {"status": "ignored", "reason": f"state={self._sm.state.value}"}

    def _handle_pause(self, payload: dict) -> dict:
        self._sm.transition_to(SystemState.PAUSED, reason="operator_pause")
        logger.info("System paused by operator")
        return {"status": "paused"}

    def _handle_stop(self, payload: dict) -> dict:
        self._sm.transition_to(SystemState.STOPPED, reason="operator_stop")
        logger.info("System stopped by operator")
        self._cleanup()
        return {"status": "stopped"}

    def _handle_status(self, payload: dict) -> dict:
        return self.get_status()

    def _handle_set_ai_provider(self, payload: dict) -> dict:
        """Switch the active AI provider at runtime."""
        provider = payload.get("provider", "").lower()
        if provider not in ("grok", "gemini"):
            return {"error": f"Invalid provider: '{provider}'. Must be 'grok' or 'gemini'."}
        self._active_ai_provider = provider
        if self._workflow:
            self._workflow.set_ai_provider(provider)
        logger.info("AI provider switched to: %s", provider)
        return {"status": "ai_provider_set", "active_ai_provider": provider}

    # ------------------------------------------------------------------
    # Image processing entry point
    # ------------------------------------------------------------------

    def on_image_received(self, image_data: bytes, device_id: str = "") -> None:
        """
        Called when the capture phone sends a new image.
        Routes it to calibration or the workflow engine.
        """
        # --- Calibration routing ---
        if self._sm.state == SystemState.CALIBRATION and self._calibration_pending:
            self._calibration_pending = False
            self._run_calibration(image_data)
            return

        if self._sm.state != SystemState.RUNNING:
            logger.debug("Image received but system is %s — ignoring", self._sm.state.value)
            return

        if self._workflow is None:
            logger.error("Workflow engine not initialized")
            return

        # Check if workflow engine is waiting for a scroll frame
        if not self._workflow._scroll_frame_event.is_set() and self._workflow._scroll_frame_data is None and self._workflow._sm.state == SystemState.RUNNING:
            # It might be waiting. We will route to receive_scroll_frame. 
            # Note: the workflow engine sets the event initially to False during scroll iteration.
            # To be safe and thread-clean, we just call the method, which sets the event.
            # But we only want to do that if it IS actually waiting.
            pass # Actually, let's look at workflow_engine state.
            
        # The safest way to know if it's waiting for a scroll frame is to add a flag `is_waiting_for_scroll`.
        
        # We will use an internal flag check here.
        if getattr(self._workflow, 'is_waiting_for_scroll', False):
            logger.info("Routing image as scroll frame")
            self._workflow.receive_scroll_frame(image_data)
            return

        if getattr(self._workflow, 'is_waiting_for_mapping', False):
            logger.info("Routing image as post-AI mapping frame")
            self._workflow.receive_mapping_frame(image_data)
            return

        if getattr(self._workflow, 'is_waiting_for_verification', False):
            logger.info("Routing image as verification frame")
            self._workflow.receive_verification_frame(image_data)
            return

        self._enqueue_primary_frame(image_data, device_id)

    def _enqueue_primary_frame(self, image_data: bytes, device_id: str) -> None:
        """Queue a primary question frame for background processing."""
        with self._processing_lock:
            if self._processing_active:
                # Keep only the latest pending frame while busy.
                self._pending_primary_frame = (image_data, device_id)
                logger.debug("Primary frame queued as pending while processor busy")
                return
            self._processing_active = True

        t = threading.Thread(
            target=self._process_primary_frame_async,
            args=(image_data, device_id),
            daemon=True,
            name="primary-frame-processor",
        )
        t.start()

    def _process_primary_frame_async(self, image_data: bytes, device_id: str) -> None:
        """Run heavy workflow processing off the API thread."""
        try:
            workflow = self._workflow
            if workflow is None:
                logger.error("Workflow engine not initialized")
                return

            decision = workflow.process_question(image_data)

            if decision and decision.outcome.value == "conflict":
                self._last_conflict_decision = {
                    "click_letter": decision.click_letter,
                    "match_result": decision.match_result,
                    "conflict": decision.conflict,
                }

            if decision and decision.outcome.value == "click":
                # STOP/PAUSE may have been issued while processing.
                if self._sm.state != SystemState.RUNNING:
                    logger.info("Skipping advance_to_next — state is %s", self._sm.state.value)
                    return
                if self._workflow is None:
                    logger.info("Skipping advance_to_next — workflow cleaned up")
                    return
                self._workflow.advance_to_next()
                # Trigger the next capture after a brief delay for the screen to settle
                self._schedule_timer(1.5, self._request_capture)

        except PiConnectionError as e:
            logger.error("Pi connection error during processing: %s", e)
            self._sm.force_error(f"pi_not_connected:{e}")
            self._alert_mgr.raise_alert(
                AlertType.INPUT_FAILURE,
                f"Pi not connected during click: {e}. Start Pi listener and press CONTINUE.",
            )
        except PiCommandError as e:
            logger.error("Pi command failed during processing: %s", e)
            self._sm.force_error(f"pi_command_failed:{e}")
            self._alert_mgr.raise_alert(
                AlertType.INPUT_FAILURE,
                f"Pi command failed: {e}. Check USB cable and Pi HID, then press CONTINUE.",
            )
        finally:
            next_item: Optional[tuple[bytes, str]] = None
            with self._processing_lock:
                if self._pending_primary_frame is not None:
                    next_item = self._pending_primary_frame
                    self._pending_primary_frame = None
                    self._processing_active = True
                else:
                    self._processing_active = False
            if next_item is not None:
                self._process_primary_frame_async(next_item[0], next_item[1])

    def on_stream_frame_received(self, image_data: bytes, device_id: str = "", seq: int | None = None) -> None:
        """
        Called when the capture phone sends a streamed frame over WS.

        We keep only the latest JPEG bytes in-memory per device_id.
        (Deterministic replay still uses the authoritative CAPTURE_IMAGE uploads.)
        """
        if not image_data:
            return
        with self._stream_frames_lock:
            self._latest_stream_frames[device_id] = image_data
            self._latest_stream_seq[device_id] = seq

    def _request_capture(self) -> None:
        """Send CAPTURE_IMAGE command to the capture phone via WebSocket."""
        if self._sm.state != SystemState.RUNNING:
            logger.debug("Not requesting capture — state is %s", self._sm.state.value)
            return

        import asyncio
        from controller.mobile_api import api_server
        if api_server._event_loop:
            asyncio.run_coroutine_threadsafe(
                api_server.registry.broadcast_to_role("capture", {
                    "type": "REMOTE_COMMAND",
                    "payload": {"command": "CAPTURE_IMAGE"}
                }),
                api_server._event_loop,
            )
            logger.info("Capture requested from phone")
        else:
            logger.warning("Event loop not available — cannot request capture")

    # ------------------------------------------------------------------
    # Calibration execution
    # ------------------------------------------------------------------

    def _run_calibration(self, image_data: bytes) -> None:
        """Run calibration from a captured image."""
        from datetime import datetime, timezone
        from calibration.coordinate_solver import calibrate_from_screenshot
        from calibration.grid_mapper import GridMap

        # Save calibration image
        cal_dir = Path("runs") / "calibration"
        cal_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        img_path = cal_dir / f"calibration_{ts}.jpg"
        img_path.write_bytes(image_data)
        logger.info("Calibration image saved: %s (%d bytes)", img_path, len(image_data))

        # Run OpenCV detection
        result = calibrate_from_screenshot(img_path)

        if result.success:
            result.grid_map.save()  # saves to config/grid_map.json
            # Create/update header anchor template used for anchored preprocessing.
            # This is best-effort: failures should not break calibration.
            try:
                from controller.capture_pipeline.header_anchor import HeaderAnchor

                HeaderAnchor.ensure_template_from_image(img_path, force=True)
            except Exception as e:
                logger.debug("Header anchor template update failed: %s", e)
            logger.info(
                "Calibration successful: %d positions mapped",
                len(result.grid_map.positions),
            )
            positions_data = {
                k: list(v) for k, v in result.grid_map.positions.items()
            }
            # Decide where to go after calibration:
            # - If we were previously RUNNING or PAUSED, resume that state
            #   and request a fresh capture so the workflow continues.
            # - Otherwise, return to IDLE.
            previous = self._state_before_calibration
            self._state_before_calibration = None

            if previous in (SystemState.RUNNING, SystemState.PAUSED) and self._workflow:
                # Pause and await explicit operator CONTINUE before resuming.
                self._sm.transition_to(SystemState.PAUSED, reason="calibration_complete_wait_continue")
                self._broadcast_calibration_result(True, positions_data)
                self._alert_mgr.raise_alert(
                    AlertType.CALIBRATION_COMPLETE,
                    "Calibration successful. Press CONTINUE on the remote phone to resume.",
                )
            else:
                # Initial calibration from START: stay IDLE and wait for CONTINUE (which will start pending run).
                self._sm.transition_to(SystemState.IDLE, reason="calibration_complete")
                self._broadcast_calibration_result(True, positions_data)
                if self._pending_start_payload is not None:
                    self._alert_mgr.raise_alert(
                        AlertType.CALIBRATION_COMPLETE,
                        "Calibration successful. Press CONTINUE on the remote phone to start.",
                    )
        else:
            logger.warning(
                "Calibration failed: %s — existing grid_map.json left unchanged",
                result.message,
            )
            # Do not overwrite the existing grid map with defaults; require operator to fix framing.
            # If calibration failed during an active/paused run, stay PAUSED and wait for retry.
            previous = self._state_before_calibration
            self._state_before_calibration = None
            if previous in (SystemState.RUNNING, SystemState.PAUSED) and self._workflow:
                self._sm.transition_to(SystemState.PAUSED, reason="calibration_failed_wait_retry")
            else:
                self._sm.transition_to(SystemState.IDLE, reason="calibration_failed")
            self._broadcast_calibration_result(False, {}, result.message)
            self._alert_mgr.raise_alert(
                AlertType.CALIBRATION_FAILED,
                f"Calibration failed: {result.message}",
            )

    def _broadcast_calibration_result(
        self, success: bool, positions: dict, error: str = ""
    ) -> None:
        """Broadcast calibration result to the capture and remote phones."""
        import asyncio
        from controller.mobile_api import api_server

        message = {
            "type": "CALIBRATION_RESULT",
            "payload": {
                "success": success,
                "positions": positions,
                "error": error,
            },
        }

        if api_server._event_loop:
            asyncio.run_coroutine_threadsafe(
                api_server.registry.broadcast_to_role("capture", message),
                api_server._event_loop,
            )
            asyncio.run_coroutine_threadsafe(
                api_server.registry.broadcast_to_role("remote_control", message),
                api_server._event_loop,
            )
        logger.info("Calibration result broadcast: success=%s", success)

    # ------------------------------------------------------------------
    # Operator decision handling
    # ------------------------------------------------------------------

    def handle_operator_decision(self, decision_str: str) -> None:
        """
        Process an operator decision in response to an alert.

        After resolving the alert, executes the appropriate action:
            SKIP_QUESTION: advance to next without answering
            USE_DATABASE_ANSWER: click the DB answer
            USE_AI_ANSWER: click the AI answer
            REQUERY_AI: re-send current question to Grok
        """
        try:
            decision = OperatorDecision(decision_str)
        except ValueError:
            logger.error("Invalid operator decision: %s", decision_str)
            return

        logger.info("Operator decision: %s", decision.value)
        self._alert_mgr.resolve_alert(decision)

        if self._sm.state != SystemState.ERROR:
            logger.warning("Operator decision received but state is %s, not ERROR", self._sm.state.value)
            return

        self._sm.transition_to(SystemState.PAUSED, reason="error_resolved")
        self._sm.transition_to(SystemState.RUNNING, reason=f"operator_{decision.value}")

        if decision == OperatorDecision.SKIP_QUESTION:
            if self._workflow:
                self._workflow.advance_to_next()
                self._schedule_next_capture(1.0)

        elif decision == OperatorDecision.USE_DATABASE_ANSWER:
            self._execute_conflict_resolution(source="database")

        elif decision == OperatorDecision.USE_AI_ANSWER:
            self._execute_conflict_resolution(source="ai")

        elif decision == OperatorDecision.REQUERY_AI:
            logger.info("Re-query AI requested — awaiting next capture for re-processing")
            self._request_capture()

        self._last_conflict_decision = None

    def _execute_conflict_resolution(self, source: str) -> None:
        """
        Execute the click for a conflict resolved by operator.
        Uses stored conflict context to determine which answer to click.
        """
        if not self._workflow or not self._last_conflict_decision:
            logger.error("No conflict context available for resolution")
            return

        conflict = self._last_conflict_decision.get("conflict")
        if conflict is None:
            logger.error("Conflict data missing from stored context")
            return

        if source == "database" and conflict.db_answer:
            from controller.answer_engine.option_matcher import match_option_by_content
            match_result = self._last_conflict_decision.get("match_result")
            if match_result and match_result.question_record:
                options = {
                    "A": match_result.question_record.get("option_a", ""),
                    "B": match_result.question_record.get("option_b", ""),
                    "C": match_result.question_record.get("option_c", ""),
                    "D": match_result.question_record.get("option_d", ""),
                    "E": match_result.question_record.get("option_e", ""),
                }
                option = match_option_by_content(conflict.db_answer, options)
                if option.found:
                    logger.info("Operator chose DB answer → clicking %s", option.matched_letter)
                    self._click_dispatcher.click_option(option.matched_letter)
                    self._workflow.advance_to_next()
                    self._schedule_next_capture(1.0)
                    return
            logger.error("Could not resolve DB answer to a clickable option")

        elif source == "ai" and conflict.ai_answer:
            from controller.answer_engine.option_matcher import match_option_by_content
            match_result = self._last_conflict_decision.get("match_result")
            if match_result and match_result.question_record:
                options = {
                    "A": match_result.question_record.get("option_a", ""),
                    "B": match_result.question_record.get("option_b", ""),
                    "C": match_result.question_record.get("option_c", ""),
                    "D": match_result.question_record.get("option_d", ""),
                    "E": match_result.question_record.get("option_e", ""),
                }
                option = match_option_by_content(conflict.ai_answer, options)
                if option.found:
                    logger.info("Operator chose AI answer → clicking %s", option.matched_letter)
                    self._click_dispatcher.click_option(option.matched_letter)
                    self._workflow.advance_to_next()
                    self._schedule_next_capture(1.0)
                    return
            logger.error("Could not resolve AI answer to a clickable option")

        self._alert_mgr.raise_alert(
            AlertType.NO_OPTION_MATCH,
            f"Could not resolve {source} answer to a clickable option",
        )
        self._sm.force_error(f"conflict_resolution_failed:{source}")

    def _schedule_next_capture(self, delay_seconds: float) -> None:
        self._schedule_timer(delay_seconds, self._request_capture)

    def _schedule_timer(self, delay_seconds: float, callback) -> None:
        """Track timers so they can be cancelled on STOP/shutdown."""
        timer_ref: dict[str, threading.Timer] = {}

        def _wrapped() -> None:
            try:
                callback()
            finally:
                t = timer_ref.get("timer")
                if t is not None:
                    with self._timers_lock:
                        if t in self._timers:
                            self._timers.remove(t)

        t = threading.Timer(delay_seconds, _wrapped)
        timer_ref["timer"] = t
        with self._timers_lock:
            self._timers.append(t)
        t.start()

    # ------------------------------------------------------------------
    # Pi connection management
    # ------------------------------------------------------------------

    def on_device_disconnected(self, device_id: str, role: str) -> None:
        """Handle device disconnection detected by heartbeat monitor."""
        logger.warning("Device disconnected: %s (role=%s)", device_id, role)
        if self._sm.state == SystemState.RUNNING:
            self._sm.force_error(f"Device disconnected: {device_id} ({role})")
            self._alert_mgr.raise_alert(
                AlertType.DEVICE_DISCONNECTED,
                f"Device '{device_id}' (role: {role}) has disconnected",
                data={"device_id": device_id, "role": role},
            )

    def connect_pi(self) -> bool:
        try:
            self._pi_client.connect()
            return True
        except PiConnectionError as e:
            logger.error("Pi connection failed: %s", e)
            return False

    def disconnect_pi(self) -> None:
        self._pi_client.disconnect()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        with self._timers_lock:
            for t in self._timers:
                try:
                    t.cancel()
                except Exception:
                    pass
            self._timers.clear()
        self._workflow = None
        self._run_ctx = None
        self._test_name = None
        self._last_conflict_decision = None

    def shutdown(self) -> None:
        logger.info("System shutting down")
        if self._sm.state not in (SystemState.STOPPED, SystemState.IDLE):
            try:
                self._sm.transition_to(SystemState.STOPPED, reason="shutdown")
            except InvalidTransitionError:
                pass
        self.disconnect_pi()
        self._db.close()
        logger.info("Shutdown complete")
