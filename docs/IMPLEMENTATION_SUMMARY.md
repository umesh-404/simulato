# SIMULATO IMPLEMENTATION SUMMARY

## Project: Simulato

Version: 1.3.1
Status: Full Implementation Complete
Last Updated: 2026-03-26

---

# 1. OVERVIEW

This document tracks the implementation status of every subsystem,
module, and compliance requirement for the Simulato platform.

All implementation follows:

- Architecture Specification
- Technical Requirements Document
- Canonical Laws (15 laws)
- Communication Protocols Specification
- Implementation Plan
- Repository Structure Specification

---

# 2. PROJECT STRUCTURE

- [x] Repository directory structure created per REPOSITORY_STRUCTURE.md (updated to match actual)
- [x] All Python packages have `__init__.py` files (17 packages)
- [x] `requirements.txt` with pinned minimum versions (includes `pytesseract`)
- [x] `config/grid_map_template.json` with default calibration data
- [x] `config/grid_map.json` (auto-generated calibration output)
- [x] `database/schema.sql` with full schema
- [x] ~62 Python files across PC controller, Raspberry Pi, calibration, scripts, and tests
- [x] ~10 Kotlin source files for Android app
- [x] 7 shell/batch scripts for deployment, replay, and debugging
- [x] 3 JSON schema files in `communication/message_schemas/`
- [x] 13 documentation files in `docs/`
- [x] 30-image calibration reference dataset in `datasets/calibration/`

---

# 3. SUBSYSTEM IMPLEMENTATION STATUS

## 3.1 Core Infrastructure

- [x] `controller/config.py` — centralized configuration (paths, network, timeouts, thresholds); PI_HOST/PI_PORT/CONTROLLER_PORT configurable via env vars
- [x] Local AI resilience controls via env:
      `OLLAMA_TIMEOUT_SECONDS` (default 20),
      `OLLAMA_TARGET_TIMEOUT_SECONDS` (default 25),
      `OLLAMA_COOLDOWN_SECONDS` (default 120),
      `OLLAMA_TIMEOUT_COOLDOWN_SECONDS` (default 6),
      `OLLAMA_KEEP_ALIVE` (default 30m)
- [x] OCR layout targeting controls via env:
      `OCR_LAYOUT_PRIMARY_ENABLED` (default True),
      `OCR_MIN_WORD_CONFIDENCE` (default 45),
      `OCR_TIMEOUT_SECONDS` (default 6),
      `OCR_PSM` (default 6),
      `TESSERACT_CMD` (optional path override)
- [x] AI retry controls:
      `AI_API_MAX_RETRIES` (default 2),
      `AI_API_BACKOFF_BASE_SECONDS` (default 1.0)
- [x] Verification frame timeout: `VERIFY_FRAME_TIMEOUT_SECONDS` (default 18)
- [x] Default AI provider: `DEFAULT_AI_PROVIDER` (default "gemini")
- [x] `controller/utils/logger.py` — file + console logging, structured EventLogger (JSONL)
- [x] `controller/utils/timer.py` — context-manager execution timer
- [x] `controller/utils/text_normalizer.py` — Unicode NFC, lowercase, whitespace collapse, numeric normalization

## 3.2 State Machine (Phase 1)

- [x] `controller/orchestrator/state_machine.py`
- [x] Six states: IDLE, CALIBRATION, RUNNING, PAUSED, ERROR, STOPPED
- [x] Explicit valid transition map enforced
- [x] IDLE → RUNNING transition supported (for direct start)
- [x] All transitions logged with source, target, and reason
- [x] `force_error()` for fail-safe from any non-STOPPED state
- [x] `InvalidTransitionError` raised on illegal transitions

## 3.3 Database Layer (Phase 2)

- [x] `database/schema.sql` — tests, questions, question_snapshots tables
- [x] `database/db_manager.py` — DatabaseManager class
- [x] SQLite with WAL journal mode and foreign keys enabled
- [x] `create_test()`, `get_test_by_name()`, `get_or_create_test()`
- [x] `store_question()` with immutable versioning (Canonical Law 7)
- [x] `answer_letter` column for storing the letter (A/B/C/D) alongside answer text
- [x] `lookup_by_hash()` — SHA256 exact match within test context
- [x] `lookup_by_simhash()` — fuzzy SimHash match with Hamming distance
- [x] `get_all_questions_for_test()` — for embedding scan
- [x] `store_snapshot()` — full question snapshot per run with optional `image_phash` (Canonical Law 10)
- [x] `lookup_by_image_phash()` — image-hash DB-first lookup (skips AI call on hit)
- [x] `_migrate_schema()` — lightweight in-place schema migration for adding `image_phash` column
- [x] JSON file export per question under `datasets/tests/<name>/questions/`
- [x] Indexes on test_id, sha256_hash, composite (test_id, sha256_hash), snapshots, image_phash

## 3.4 Question Canonicalization & Hashing (Phase 3–4)

- [x] `controller/question_engine/canonicalizer.py`
- [x] Canonical string: `normalized_question|sorted_opt1|sorted_opt2|sorted_opt3|sorted_opt4`
- [x] Options sorted by normalized content (not by letter) for shuffle resistance
- [x] `controller/question_engine/hash_engine.py`
- [x] SHA256 hex digest of canonical text
- [x] 64-bit SimHash fingerprint (token-frequency based)
- [x] Hamming distance comparison for SimHash

## 3.5 Embedding Engine (Phase 4)

- [x] `controller/question_engine/embedding_matcher.py`
- [x] Lazy-loaded `bge-small-en-v1.5` via sentence-transformers
- [x] L2-normalized embeddings (dot product = cosine similarity)
- [x] `embedding_to_bytes()` / `bytes_to_embedding()` for SQLite BLOB storage
- [x] `find_best_match()` with configurable threshold (default 0.92)

## 3.6 Cloud AI Integration — Grok Vision (Phase 5)

- [x] `controller/ai_pipeline/prompt_builder.py`
- [x] System prompt engineered for exact JSON output with `answer_content` field
- [x] Vision API message format with base64 image
- [x] `controller/ai_pipeline/response_parser.py`
- [x] Pydantic models: `GrokResponse`, `GrokResponseOptions`, `GrokErrorResponse`
- [x] JSON extraction from markdown-fenced or prose-wrapped responses
- [x] `answer_content` cross-validation against `options[answer]`
- [x] `controller/ai_pipeline/grok_client.py`
- [x] `temperature: 0` for deterministic output (Canonical Law 1)
- [x] **Structured Outputs (`response_format`)** with strict JSON Schema (Zero-parse-failure design)
- [x] **Primary Solver Role:** Exclusively responsible for question OCR and reasoning
- [x] Retry with exponential backoff (`AI_API_BACKOFF_BASE_SECONDS` * 2^attempt)
- [x] API key from environment variable

### 3.6b Cloud AI Integration — Gemini Vision

- [x] `controller/ai_pipeline/gemini_client.py`
- [x] OpenAI-compatible endpoint (generativelanguage.googleapis.com)
- [x] `temperature: 0` for deterministic output (Canonical Law 1)
- [x] Shares prompt builder and response parser with Grok client
- [x] **Default Primary Solver:** Selectable at runtime via `SET_AI_PROVIDER` command
- [x] Retry with exponential backoff (matches Grok retries)
- [x] API key from environment variable

### 3.6c Local AI Integration — Ollama/Qwen (Auxiliary)

- [x] `controller/ai_pipeline/ollama_client.py` — dedicated Ollama client module
- [x] `controller/ai_pipeline/aux_prompts.py` — task-specific prompts for all auxiliary tasks
- [x] `temperature: 0`, `seed: 42` for deterministic output
- [x] JSON format enforcement (`"format": "json"`)
- [x] Cooldown mechanism: general failures → full cooldown; timeout-only → short cooldown
- [x] `keep_alive` parameter to keep model in memory
- [x] Per-task timeout override (standard vs target timeout)
- [x] Functions: `check_needs_scroll()`, `check_is_answered()`, `check_screen_state()`,
      `locate_next_button_grid()`, `locate_option_target()`, `locate_next_button_target()`

## 3.7 Question Matcher — Staged Lookup (Phase 6)

- [x] `controller/question_engine/question_matcher.py`
- [x] Stage 1: SHA256 exact hash match
- [x] Stage 2: SimHash fuzzy match (Hamming distance ≤ 3)
- [x] Stage 3: Embedding cosine similarity (≥ 0.92)
- [x] Stage 4: AI fallback (new question)
- [x] All lookups scoped to active test context
- [x] `MatchResult` carries source, record, canonical text, hashes, embedding

## 3.8 Answer Engine (Phase 7)

- [x] `controller/answer_engine/option_matcher.py`
- [x] Two-pass matching: exact normalized → substring containment
- [x] Matches by text content, never by letter position (Canonical Law 8)
- [x] `controller/answer_engine/conflict_handler.py`
- [x] AI vs DB conflict detection via normalized comparison (Canonical Law 9)
- [x] Conflict payload with both answers and question ID
- [x] `controller/answer_engine/decision_engine.py`
- [x] **DB-first path:** DB answer → conflict check → option match → click (no Grok/Gemini call when a DB match exists)
- [x] **Image-hash fast path:** pHash match → use cached answer letter directly (no AI call at all)
- [x] New question path: AI answer → store question → click
- [x] Conflict path: raise conflict for operator intervention

## 3.9 Hardware Control — Raspberry Pi Interface (Phase 8)

- [x] `raspberry_pi/hid_controller.py`
- [x] **HIDPi library integration** — imports `hidpi.Mouse` for absolute clicks
- [x] Fallback to raw 6-byte reports (`<BHHb`) if HIDPi not installed
- [x] Absolute pointer coordinates (0–32767 range)
- [x] Scroll wheel support via HIDPi `Mouse.scroll()`
- [x] `raspberry_pi/device_config.py` — `hidg0` = keyboard, `hidg1` = mouse (matches HIDPi descriptor)
- [x] `controller/hardware_control/pi_client.py`
- [x] TCP socket client with JSON protocol
- [x] Command validation against VALID_COMMANDS set
- [x] Retry up to COMMAND_MAX_RETRIES (3) with ACK timeout (3s)
- [x] `PiConnectionError` / `PiCommandError` exceptions
- [x] `controller/hardware_control/click_dispatcher.py`
- [x] Letter-to-command mapping (A→CLICK_A, etc.)
- [x] Calibrated grid→pixel→absolute HID coordinate conversion for all
      clicks (options, NEXT, scroll regions)
- [x] `click_at_normalized()` — accepts normalized (0–1) coordinates from OCR/Qwen
- [x] Local-AI-assisted NEXT targeting when available
- [x] `click_option()`, `click_next()`, `scroll_left()`, `scroll_right()`
- [x] `controller/hardware_control/verification_engine.py`
- [x] Post-click screenshot capture via callback
- [x] HSV color space highlight detection with grid-based region cropping
- [x] Before/after screenshot comparison for highlight change detection
- [x] Fallback full-image blue-ratio analysis

## 3.10 Capture Pipeline (Phase 9)

- [x] `controller/capture_pipeline/image_receiver.py`
- [x] Deterministic file naming: `capture_NNNN_timestamp.jpg`
- [x] Base64 and raw bytes reception
- [x] Public `run_dir` property for artifact access
- [x] `latest_path` tracking for newest frame
- [x] Routing support for scroll frames and post-click verification frames
- [x] `controller/capture_pipeline/scroll_detector.py`
- [x] **v4 structural scroll detection** (rewritten from brightness-based v3)
- [x] `_find_ui_bounds()` — isolates exam UI content from dark photo borders using column brightness analysis (threshold 130) with run-length filtering
- [x] `_detect_scrollbar_structural()` — profile-range + dip-std detection: computes column-mean brightness profile across rightmost 100 columns of middle 60% panel height, detects scrollbar when profile range > 10 and column std at minimum < 20
- [x] `_detect_cutoff_structural()` — bottom-edge content cutoff via Canny edge density
- [x] `DualPanelScrollResult` — independent scroll detection for question and answer panels
- [x] Calibration accuracy: 90% overall (27/30), 0 false positives on no-scroll images
- [x] Known limitation: Q-panel scrollbar detection unreliable (text content noise masks signal)
- [x] `controller/capture_pipeline/image_stitcher.py`
- [x] Vertical stitching with width normalization via OpenCV
- [x] Single-frame passthrough (copy, no stitch)
- [x] `controller/capture_pipeline/image_preprocessor.py`
- [x] CLAHE contrast enhancement
- [x] Resolution validation warning

### 3.10a Screen Validation

- [x] `controller/capture_pipeline/screen_validator.py`
- [x] 5-check validation pipeline: dimensions, blank detection, edge density, zone distribution, uniform region detection
- [x] Content zone analysis (vertical thirds)
- [x] Abnormal screen detection (login/error screens via uniform color blocks)

### 3.10b OCR Layout Analyzer (NEW)

- [x] `controller/capture_pipeline/ocr_layout_analyzer.py`
- [x] Tesseract OCR integration for full-screen word extraction
- [x] Per-word confidence filtering (`OCR_MIN_WORD_CONFIDENCE`)
- [x] `OCRWord` dataclass with text, confidence, bounding box, and center properties
- [x] `OCRLayoutResult.locate_option_target(letter)` — finds option anchor text and returns normalized click coordinates
- [x] `OCRLayoutResult.locate_next_target()` — finds NEXT button text and returns normalized click coordinates
- [x] Letter anchor detection via regex cleaning, preferring high-confidence anchors near left side
- [x] Row-band grouping to find option text row and offset click target left to hit radio area
- [x] Primary click-targeting method used before falling back to Local AI or calibrated grid

### 3.10c Exam Layout Detector (NEW)

- [x] `controller/capture_pipeline/exam_layout.py`
- [x] Detects split-pane exam UI: question panel (left), answer panel (right), vertical divider
- [x] `ExamLayout` dataclass with question_panel, answer_panel, divider_x, bottom_bar, next/prev/clear buttons, nav_sidebar, header
- [x] `ExamLayoutDetector.detect()` — Sobel-X edge detection + column projection for finding vertical divider
- [x] Fallback divider handle detection via dark-dot pattern analysis
- [x] Bottom-bar button detection via OCR with fallback to fixed positions
- [x] Tunable thresholds for divider search region, header/bar fractions, grayscale intensity range

### 3.10d Option Detector (NEW)

- [x] `controller/capture_pipeline/option_detector.py`
- [x] Y-clustering approach for radio button detection
- [x] HoughCircles on narrow left-edge strip of the answer panel
- [x] Y-coordinate clustering to group noisy circle candidates into radio-button rows
- [x] Supports 3–5 options (A through E)
- [x] Per-option OCR text extraction with upscaling for small regions
- [x] `DetectedOption` dataclass with label, text, circle coordinates, click coordinates, bounds, confidence
- [x] `OptionMap` with `get(label)` and normalized coordinate conversion

## 3.11 Alert System (Phase 11)

- [x] `controller/alerts/alert_manager.py`
- [x] AlertType enum: AI_CONFLICT, INPUT_FAILURE, UNEXPECTED_SCREEN, DEVICE_DISCONNECTED, AI_PARSE_FAILURE, VERIFICATION_FAILURE, CALIBRATION_REQUIRED, CALIBRATION_FAILED, CALIBRATION_COMPLETE, TEST_COMPLETE
- [x] OperatorDecision enum: REQUERY_AI, SKIP_QUESTION, USE_DATABASE_ANSWER, USE_AI_ANSWER
- [x] Sound callback wired to `play_alarm()`
- [x] Notify callback wired to `queue_alert_for_broadcast()` (WebSocket relay)
- [x] `controller/alerts/sound_player.py`
- [x] Platform-aware playback: winsound (Windows), afplay (macOS), aplay (Linux)
- [x] Fallback to system beep

## 3.12 FastAPI Server — Mobile Communication (Phase 10)

- [x] `controller/mobile_api/api_server.py`
- [x] `POST /api/register` — device registration with role
- [x] `POST /api/heartbeat` — heartbeat acknowledgement
- [x] `POST /api/upload_image` — image upload from capture phone
- [x] `POST /api/command` — remote commands (CALIBRATE, START, CONTINUE, PAUSE, STOP, STATUS, SET_AI_PROVIDER)
- [x] `POST /api/operator_decision` — operator conflict resolution
- [x] `GET /api/status` — system status query
- [x] `WS /ws/{device_id}` — WebSocket for real-time alerts + heartbeats
- [x] DeviceRegistry with heartbeat tracking
- [x] Thread-safe alert queue (`queue_alert_for_broadcast`)
- [x] Background task: alert flush loop (0.5s interval)
- [x] Background task: heartbeat monitor (5s interval, 15s timeout)
- [x] Disconnection callback to SystemController
- [x] Command guard: `START`/`CALIBRATE` rejected when no capture device is connected

## 3.13 Replay Engine (Phase 12)

- [x] `controller/replay/run_loader.py`
- [x] `create_run()` — timestamped run directory with artifact subdirs
- [x] `list_runs()` — enumerate existing runs
- [x] `controller/replay/replay_engine.py`
- [x] `ReplayRun` loads events.jsonl
- [x] `ReplayEngine.replay_run()` loads events, replays each answer_decision
- [x] Per-question re-execution: loads stored AI JSON → re-runs decide_answer() → compares
- [x] `ReplayReport` with match/mismatch/error tracking and summary generation
- [x] `run_loader.py` — `list_runs()`, `load_run()`, `RunMetadata` with completeness check

## 3.14 Orchestrator — System Controller & Workflow (Phase 1 continued)

- [x] `controller/orchestrator/system_controller.py`
- [x] Wires all subsystems: state machine, DB, alerts, Pi, click dispatcher, verification
- [x] Command routing: CALIBRATE, START, CONTINUE, PAUSE, STOP, STATUS, SET_AI_PROVIDER
- [x] Image routing to workflow engine
- [x] Operator decision handling with conflict resolution
- [x] USE_DATABASE_ANSWER / USE_AI_ANSWER execute the actual click
- [x] SKIP_QUESTION advances to next
- [x] REQUERY_AI logs intent (awaits next capture)
- [x] Device disconnection handler triggers ERROR + alert
- [x] Graceful shutdown with state transition and cleanup
- [x] `controller/orchestrator/workflow_engine.py`
- [x] Full 10-step question processing pipeline
- [x] Screen validation (fail-safe)
- [x] Scroll detection
- [x] **Scroll-and-recapture loop** — wait for scroll frame via WebSocket + stitch
- [x] Image stitching
- [x] Image preprocessing
- [x] **OCR layout pass** (primary click-targeting, deterministic, runs on every processed frame)
- [x] **Image-hash (pHash) DB-first lookup** — bypasses AI call entirely when a previously seen image is captured
- [x] **Tiered AI Integration:** Grok (Cloud) and Gemini (Cloud) as selectable primary solvers, Ollama (Local/Qwen) as auxiliary analyst
- [x] **Cloud-provider failover:** if the selected primary provider fails (transport/parse), workflow retries once with the alternate provider before raising AI_PARSE_FAILURE
- [x] **Runtime AI Provider Switching:** `SET_AI_PROVIDER` command from Remote Control phone dropdown
- [x] **Local AI Task Suite:** Scroll verification (initial + each scroll frame), answer state checking using dedicated verification captures, NEXT button localization, screen classification (QUESTION/LOGIN/ERROR/OTHER) with timeout+cooldown safeguards
- [x] **Click targeting hierarchy:** OCR (primary) → Local Qwen (secondary) → calibrated grid (fallback)
- [x] Answer decision engine integration
- [x] Click execution with `_verify_option_click()` (Local AI or CV) + retry + alert (Law 5)
- [x] Strict local-AI verification enforces selected option letter must match the clicked letter (not just "any option selected")
- [x] NEXT click with verification + retry + alert (Canonical Law 5)
- [x] End-of-test detection (`TEST_COMPLETE`) when screen does not change after NEXT
- [x] **Autonomous capture loop** — automatically trigger next capture after NEXT click
- [x] Full snapshot storage per question with image_phash (Canonical Law 10)
- [x] Structured event logging for replay (Canonical Law 2)

## 3.15 Raspberry Pi Side

- [x] `raspberry_pi/device_config.py` — `hidg0`=keyboard, `hidg1`=mouse (matches HIDPi)
- [x] `raspberry_pi/hid_controller.py` — HIDPi library import + 6-byte absolute mouse fallback
- [x] `raspberry_pi/command_listener.py` — TCP server, JSON protocol, command → HID execution

## 3.16 Calibration

- [x] `calibration/grid_mapper.py` — GridMap class with resolution, grid size, positions
- [x] Grid-to-pixel coordinate conversion
- [x] JSON save/load for `grid_map.json`
- [x] Default positions template (A, B, C, D, NEXT, SCROLL_LEFT, SCROLL_RIGHT)
- [x] `calibration/coordinate_solver.py` — automated calibration from screenshot
- [x] Contour-based option region detection with aspect ratio filtering
- [x] Bottom-right NEXT button detection
- [x] Pixel-to-grid coordinate mapping with resolution scaling
- [x] **End-to-end calibration workflow** — Capture Phone button → PC command routing → CAPTURE_IMAGE WS command → image upload → OpenCV detection → `grid_map.json` save → `CALIBRATION_RESULT` broadcast to phone

## 3.17 Entry Point

- [x] `controller/main.py`
- [x] Initializes SystemController
- [x] Wires all callbacks (command, image, decision, status, disconnection)
- [x] Starts FastAPI via uvicorn
- [x] Graceful shutdown on KeyboardInterrupt

---

# 4. CANONICAL LAW COMPLIANCE

| # | Law | Status | Implementation |
|---|-----|--------|---------------|
| 1 | Deterministic Execution | PASS | temperature=0 on Grok/Gemini, seed=42 on Ollama, no randomness, deterministic canonicalization |
| 2 | Replayability | PASS | EventLogger JSONL, screenshots, AI responses saved per run |
| 3 | External Interaction Only | PASS | Camera + USB HID only, no exam software modification |
| 4 | Distributed System Model | PASS | All decisions on PC, Pi executes only, phones capture/control |
| 5 | Hardware Input Transaction | PASS | Answer clicks + NEXT clicks: verify → retry → alert |
| 6 | Human Intervention Authority | PASS | Sound alarm + WebSocket alert to remote phone |
| 7 | Dataset Integrity | PASS | Immutable records with versioning, never UPDATE |
| 8 | Answer by Content | PASS | option_matcher uses normalized text, canonical sorts by content |
| 9 | AI Response Validation | PASS | AI/DB conflict → alert → operator decision required |
| 10 | Full Snapshot Storage | PASS | store_snapshot() called after every question decision (with image_phash) |
| 11 | Complete Logging | PASS | All modules log, EventLogger records structured events |
| 12 | Failure Visibility | PASS | Failures halt + alert + remote notification |
| 13 | Controller Authority | PASS | All orchestration on Main Control PC |
| 14 | System State Explicitness | PASS | 6 states, logged transitions, IDLE → RUNNING allowed |
| 15 | Network Usage | PASS | Only Grok/Gemini API uses internet, all else local |

---

# 5. COMMUNICATION PROTOCOL COMPLIANCE

- [x] JSON message format for all communication
- [x] Device registration with role (DEVICE_REGISTER / REGISTER_ACK)
- [x] Heartbeat every 5 seconds (HEARTBEAT / HEARTBEAT_ACK)
- [x] Heartbeat timeout detection (15 seconds → device disconnected)
- [x] Image upload via HTTP POST (JSON with BASE64-encoded JPEG)
- [x] Remote commands via HTTP POST (REMOTE_COMMAND / COMMAND_ACK)
- [x] Alert distribution via WebSocket (SYSTEM_ALERT)
- [x] Calibration result via WebSocket (CALIBRATION_RESULT)
- [x] Operator decisions via HTTP and WebSocket (OPERATOR_DECISION)
- [x] Pi commands via TCP socket (PI_COMMAND / PI_RESPONSE)
- [x] WebSocket URL includes device_id path param (`/ws/<device_id>`)
- [x] **WebSocket endpoint validates device registration** before accepting
- [x] Single-role enforcement (one role per device, one device per role)
- [x] Command ACK timeout: 3 seconds
- [x] Command max retries: 3
- [x] Image upload timeout: 10 seconds
- [x] Upload-image processing failures return HTTP 200 with `processing=error` while controller pauses/alerts (no capture-loop 500 storm)
- [x] START guard enforces Pi connectivity; rejects with INPUT_FAILURE when Pi listener unavailable
- [x] Bounded TCP frame buffers on both Controller Pi client and Pi listener

---

# 6. SPECIFICATION UPDATES APPLIED

- [x] Added `answer_content` field to Grok response schema in all docs
- [x] Simplified networking model — all devices join any shared WiFi network
- [x] Updated REPOSITORY_STRUCTURE.md to match actual codebase (~120 files)
- [x] Updated IMPLEMENTATION_PLAN.md (folder structure, minSdk 26, deployment steps)
- [x] Added `pytesseract` to `requirements.txt` for OCR-first layout targeting
- [x] Added OCR configuration variables to `controller/config.py` and `.env`
- [x] Added `image_phash` column to `question_snapshots` schema (via migration)
- [x] Added `answer_letter` column to `questions` schema
- [x] Added `gemini_client.py` as second cloud AI provider
- [x] Added `ollama_client.py` + `aux_prompts.py` as dedicated local AI modules
- [x] Added `exam_layout.py`, `ocr_layout_analyzer.py`, `option_detector.py` to capture pipeline
- [x] Rewrote `scroll_detector.py` from brightness-based (v3) to structural UI-aware detection (v4)
- [x] Added `pipeline_diagnosis.py` comprehensive CV pipeline diagnostic script
- [x] Added 7 calibration/debug scripts to `scripts/`
- [x] Added 30-image calibration reference dataset in `datasets/calibration/`
- [x] Added `install-and-run.bat` and `simulato.keystore` to mobile app

---

# 7. COMPLETED WORK (PREVIOUSLY REMAINING)

## 7.1 Computer Vision — COMPLETE

- [x] Real highlight detection in `verification_engine.py` (HSV color analysis + before/after diff)
- [x] Real scroll detection in `scroll_detector.py` (v4 structural: UI-bounds isolation + profile-range + dip-std, 90% accuracy on 30-image dataset)
- [x] Real screen layout validation in `screen_validator.py` (5-check pipeline)
- [x] Automated calibration workflow in `calibration/coordinate_solver.py` (contour-based)
- [x] Question change detection in `controller/capture_pipeline/change_detector.py` (pHash via DCT)
- [x] Exam layout detection in `capture_pipeline/exam_layout.py` (split-pane divider via Sobel-X)
- [x] Option radio button detection in `capture_pipeline/option_detector.py` (HoughCircles + Y-clustering)
- [x] OCR-first click targeting in `capture_pipeline/ocr_layout_analyzer.py` (Tesseract)

## 7.2 Android Application — COMPLETE

- [x] Single Android APK with Capture Mode + Remote Control Mode
- [x] Home screen role selection (`HomeActivity`) with controller IP/port configuration
- [x] Camera preview with zoom control (`CaptureActivity` using CameraX) — zoom step: 0.1x
- [x] Image upload to PC controller via base64 JSON HTTP POST (`/api/upload_image`)
- [x] **CALIBRATE SCREEN MAP button on Capture Mode phone** — triggers end-to-end calibration
- [x] Remote control buttons: START, PAUSE, STOP, STATUS (`RemoteControlActivity`)
- [x] Alert display with vibration and AlertDialog (`RemoteControlActivity`)
- [x] Operator decision UI: REQUERY_AI, SKIP_QUESTION, USE_DATABASE_ANSWER, USE_AI_ANSWER
- [x] WebSocket connection with device_id path param (`ws://<ip>:<port>/ws/<device_id>`)
- [x] WebSocket handles: SYSTEM_ALERT, REMOTE_COMMAND, CALIBRATION_RESULT
- [x] Autonomous capture — PC sends CAPTURE_IMAGE via WS → phone captures and uploads
- [x] Single-role enforcement on server — one device per role at a time
- [x] Heartbeat manager (`HeartbeatManager`) + foreground service (`HeartbeatService`)
- [x] Mobile auto re-registration flow on repeated heartbeat failures / `device not registered` responses
- [x] `HeartbeatService` hardened: single-start guard, role-aware register, and automatic re-register callback
- [x] `android:usesCleartextTraffic="true"` in AndroidManifest.xml
- [x] Release APK signing and build (`simulato.keystore` + `install-and-run.bat`)

## 7.3 Integration & Testing — COMPLETE

- [x] End-to-end test: Pi HID verified on Pi 5 with connected host
- [x] Android APK built and installed on Capture + Remote phones
- [ ] Full 5-device integration test (requires exam laptop + all devices on WiFi)
- [x] Unit tests for canonicalizer (10 tests — all pass)
- [x] Unit tests for hash engine (16 tests — all pass)
- [x] Unit tests for option matcher (9 tests — all pass)
- [x] Unit tests for state machine transitions (27 tests — all pass)
- [x] Integration test: question matcher pipeline (8 tests — requires sentence-transformers)
- [x] Integration test: workflow engine cycle (9 tests — all pass)
- [x] Replay engine: full decision re-execution (`ReplayEngine.replay_run()`)
- [ ] Performance benchmarking against TRD targets (requires hardware + real data)
- [x] 30-image calibration dataset for CV pipeline calibration/validation

## 7.4 Deployment — COMPLETE

- [x] Pi USB HID gadget mode via HIDPi (`HIDPi/HIDPi_Setup.py` + systemd service)
- [x] Pi startup script (`start_pi.sh`) — handles HIDPi check + listener
- [x] PC startup script (`start.bat`) — auto-starts Ollama + auto-pulls model + warmup + starts controller
- [x] Linux controller startup script (`scripts/start_controller.sh`)
- [x] Windows controller startup script (`scripts/start_controller.bat`)
- [x] Windows controller stop script (`scripts/stop_controller.bat`)
- [x] WiFi network configuration guide (`docs/WIFI_SETUP_GUIDE.md`)
- [x] Deployment checklist document (`docs/DEPLOYMENT_CHECKLIST.md`)
- [x] Replay run script (`scripts/replay_run.sh`)
- [x] Top-level `README.md` with 5-device deployment guide
- [x] **Complete setup guide** (`docs/SETUP_GUIDE.md`) — zero-to-running for all devices

## 7.5 Scripts & Tooling

- [x] `scripts/pi_smoke_test.py` — HID click smoke test from Mother PC (center/corners/grid patterns)
- [x] `scripts/calibrate_cv_pipeline.py` — runs CV pipeline calibration across 30-image dataset
- [x] `scripts/calibrate_scroll.py` — scroll detection calibration
- [x] `scripts/debug_scroll.py` — scroll detection debugging
- [x] `scripts/scroll_diagnosis.py` — scroll analysis diagnostics
- [x] `scripts/measure_radio.py` — radio button measurement tool
- [x] `scripts/measure_scroll.py` — scroll bar measurement tool
- [x] `scripts/pipeline_diagnosis.py` — comprehensive CV pipeline diagnostic (runs layout + option + scroll detection against calibration dataset, generates annotated debug images and JSON report)
- [x] `clean_imports.py` / `restore_imports.py` — import path management utilities

## 7.6 Remaining (Hardware-Dependent)

- [ ] End-to-end test with real hardware
- [ ] Performance benchmarking with real exam data
- [ ] CV algorithm tuning with real exam screenshots (beyond 30-image dataset)
- [ ] Q-panel scrollbar detection improvement (current method unreliable due to text noise)

---

# 8. FILE COUNT

| Category | Files |
|----------|-------|
| Python (controller/) | 49 |
| Python (database/) | 2 |
| Python (raspberry_pi/) | 4 |
| Python (calibration/) | 3 |
| Python (scripts/) | 8 |
| Python (root utilities) | 2 |
| SQL | 1 |
| JSON (schemas + config) | 5 |
| Docs (md) | 13 |
| Shell/batch scripts | 7 |
| Android/Kotlin source | 12 |
| Android XML (manifests + layouts + resources) | 7 |
| Android Gradle/config | 6 |
| Android build artifacts | 1 |
| requirements.txt | 1 |
| **Total** | **~120** |

---

# END OF IMPLEMENTATION SUMMARY
