# SIMULATO SYSTEM ARCHITECTURE SPECIFICATION

## Project: Simulato

Version: 1.5.0\
Status: Authoritative Architecture Specification\
Last Updated: 2026-03-29

------------------------------------------------------------------------

# 1. PURPOSE

This document defines the **authoritative technical architecture** of
the Simulato system.

Simulato is a distributed automation platform designed to simulate
AI‑assisted exam solving workflows using external observation and input
injection.

The architecture is designed to guarantee:

-   deterministic execution
-   reproducible experiments
-   distributed device coordination
-   safe hardware input automation
-   dataset integrity
-   traceable experiment runs

This specification aligns with:

-   Business Requirements Document (BRD)
-   Technical Requirements Document (TRD)
-   Implementation Plan
-   Simulato Canonical Laws

If any implementation conflicts with this architecture, the architecture
specification takes precedence.

------------------------------------------------------------------------

# 2. HIGH LEVEL SYSTEM OVERVIEW

Simulato operates as a **distributed five‑node system**.

Nodes:

1.  Exam Laptop
2.  Raspberry Pi HID Injector
3.  Main Control PC (System Brain)
4.  Capture Phone
5.  Remote Control Phone

System topology:

Exam Laptop\
↑\
Raspberry Pi (USB HID Injector)\
↑\
Main Control PC (Orchestrator)\
↑\
Capture Phone (Camera Input)\
↑\
Remote Control Phone (Operator Control)

The **Main Control PC acts as the central orchestrator** for the entire
system.

------------------------------------------------------------------------

# 3. DEVICE ROLES AND RESPONSIBILITIES

------------------------------------------------------------------------

## 3.1 Exam Laptop

The exam laptop runs the secure exam environment.

Responsibilities:

-   Display exam interface
-   Accept mouse input
-   Accept keyboard input

Restrictions:

-   No software modifications
-   No internal automation
-   No injected software components

Interaction occurs only through:

-   screen observation
-   USB input devices

------------------------------------------------------------------------

## 3.2 Raspberry Pi HID Injector

The Raspberry Pi acts as a **hardware input emulator**.

Connection:

USB connection to exam laptop.

Capabilities:

-   emulate mouse movement
-   emulate mouse clicks
-   emulate keyboard input

Supported commands:

CLICK_A\
CLICK_B\
CLICK_C\
CLICK_D\
CLICK_E\
CLICK_NEXT\
SCROLL_LEFT\
SCROLL_RIGHT\
SCROLL_DOWN\
SCROLL_UP

The Pi receives commands from the **Main Control PC** and executes them
deterministically.

No AI processing occurs on the Pi.

------------------------------------------------------------------------

## 3.3 Main Control PC

The Main Control PC is the **central orchestration node**.

Responsibilities:

-   receive images from capture phone
-   detect question boundaries
-   detect scrolling requirements
-   stitch image segments
-   call Cloud AI (Vertex AI Gemini) for question solving — **always, for every question**
-   call Local AI (Ollama/Qwen) for auxiliary screen analysis (scroll/answer verification)
-   process structured AI responses (via `response_format`)
-   determine answer actions from AI response
-   dispatch commands to Raspberry Pi
-   verify input results
-   manage system state
-   log all events
-   manage alerts
-   manage operator interventions

All decision making occurs on this node.

------------------------------------------------------------------------

## 3.4 Capture Phone

The capture phone provides the **visual observation system**.

This device runs the **Simulato Android Application** in **Capture Mode**.

Responsibilities:

-   capture images of exam screen
-   allow zoom adjustments
-   send captured images to Main Control PC

Image capture requirements:

-   use native phone camera pipeline
-   enable HDR
-   ensure sharp text capture

Images must be sent via local network to the PC.

------------------------------------------------------------------------

## 3.5 Remote Control Phone

The remote control phone provides the **operator interface**.

This device runs the **Simulato Android Application** in **Remote Control Mode**.

Controls:

START
PAUSE
STOP
STATUS
RECALIBRATE (optional, mid-exam)

Alert Handling:

When the system encounters an issue, the remote device displays:

-   alert message
-   decision options

Operator options:

-   re-query AI
-   skip question
-   continue with database answer
-   continue with AI answer

------------------------------------------------------------------------

## 3.6 Mobile Application Architecture

Both the Capture Phone (node 4) and Remote Control Phone (node 5) run a
**single Android application** with **two operational modes**.

App Modes:

1.  **Capture Mode** — provides camera-based screen capture and image upload
2.  **Remote Control Mode** — provides operator control interface and alert handling

The mode is selected from the **application home screen** at startup.

The application must allow switching between modes **without reinstalling
or restarting the app**.

------------------------------------------------------------------------

## 3.7 Mobile Device Role Assignment

Because both phones run the same application, the system must enforce
**unique device role assignment**.

At startup, the application presents:

    Select Device Role

    [ Capture Device ]
    [ Remote Controller ]

This prevents two phones from both entering Capture Mode or both entering
Remote Control Mode.

The selected role determines which operational mode the app enters and
which API endpoints it communicates with on the Main Control PC.

------------------------------------------------------------------------

# 4. SYSTEM STATES

The system operates using an explicit state machine.

States:

IDLE
CALIBRATION
RUNNING
PAUSED
ERROR
STOPPED

State transitions are controlled by the Main Control PC.

All transitions must be logged.

------------------------------------------------------------------------

# 5. CALIBRATION PROCESS

Calibration establishes coordinate mapping between the captured image
and screen grid.

The system must be **successfully calibrated before any run may enter
RUNNING state**. A valid calibration is represented by a usable
`grid_map.json` file.

If START is requested while no valid calibration exists, the controller
automatically enters calibration first, then waits for explicit operator
`CONTINUE` confirmation before starting the run.

### 5.1 Initial calibration

Steps:

1.  Operator positions capture phone
2.  Operator presses CALIBRATE on the Capture Phone, or START triggers
    automatic calibration from the Remote Control flow
3.  Capture phone sends screen image
4.  PC detects exam layout
5.  PC constructs grid map
6.  Coordinates saved to configuration
7.  PC sends `CALIBRATION_RESULT` to both phones
8.  Capture phone shows a short (2–3 second) “Calibration successful”
    confirmation
9.  Remote phone shows blocking confirmation; operator presses CONTINUE
    to start/resume pipeline

Output file:

grid_map.json

Grid example:

resolution: 1920x1080
grid: 20x20

Example grid mapping:

A = (15,8)
B = (15,10)
C = (15,12)
D = (15,14)
NEXT = (18,19)

The grid map also stores **exact screen-space pixel coordinates**
(`pixel_positions`) for all detected option and NEXT positions.
These are preferred over grid-quantized positions for verification
coordinate lookups, avoiding rounding drift.

**Capture → exam-screen transform (runtime clicks):** `grid_map.json`
includes `capture_resolution` and a linear `transform` object
(`scale_x`, `scale_y`, `offset_x`, `offset_y`). The controller
converts normalized capture coordinates to capture pixels, then applies
`capture_to_screen_pixel()` before HID mapping. A naive scale of
`screen_resolution / capture_resolution` assumes an undistorted,
front-on view; angled phone photography introduces perspective error
that manifests as consistent vertical (or horizontal) targeting drift.
Non-zero offsets and/or adjusted scales correct this; re-calibration
reuses a non-naive transform already on disk when present so operators
do not lose a verified mapping.

### 5.2 Option Detection (HoughCircles)

Radio button detection uses adaptive multi-strip HoughCircles scanning
across the answer panel:

-   Search strips span the leftmost 16% of the panel width at 2%
    increments (8 strips total), covering the actual radio-button column
    reliably.
-   A calibration-guided minimum Y filter rejects "Answer here" header
    phantoms using the calibrated option-A position as a floor.
-   Post-detection spacing outlier removal handles any remaining phantom
    rows above or below real options.
-   Labels are assigned via calibration-anchored Y-proximity matching
    (works for 3–5 detected circles), ensuring correct A–E mapping even
    when one or more circles are missed.
-   A recovery pass (targeted narrow-band HoughCircles) is retained as a
    last-resort fallback but rarely triggers with the corrected search
    range.

------------------------------------------------------------------------

# 6. QUESTION CAPTURE PIPELINE

For each question:

1.  capture screenshot from the Capture Phone
    (Capture Phone may upload a cached streamed frame when `CAPTURE_IMAGE` is requested.)
2.  run **scroll requirement detection** on the Main Control PC:
    -   if `LOCAL_AI_ASSIST_ENABLED=True`: use OCR bottom-edge truncation heuristic (confidence-gated)
        and fall back to Ollama `SCROLL_CHECK_PROMPT`
    -   else: run the **local CV scroll detection pipeline** v4 (`exam_layout.py` + `scroll_detector.py`)
3.  if scrolling is needed:
    -   command the Pi to scroll via HID
    -   request additional captures from the Capture Phone
    -   repeat scroll detection on each scroll frame until content is fully visible
4.  stitch all frames into a full question image
5.  send stitched image to cloud AI only for solve/context
6.  request one fresh post-AI mapping capture and rebuild live option/NEXT targets from that frame

### 6.1 Scroll Detection Pipeline (v4)

Scroll detection is performed with a tiered strategy on the Main Control PC:
- If `LOCAL_AI_ASSIST_ENABLED=True`, the system first uses an OCR truncation
  heuristic (bottom-edge text bounding boxes) and only calls Ollama when
  the heuristic confidence is low.
- If `LOCAL_AI_ASSIST_ENABLED=False`, scroll detection runs entirely via
  **local Computer Vision** (no AI calls).

The detector operates in two stages:

1.  **UI Bounds Isolation** — identifies the actual exam UI content area
    within the phone-captured image by finding the brightness transition
    between the white exam background (column mean > 130) and the dark
    photo border (column mean < 80).

2.  **Profile-Range + Dip-Std Detection** — within the isolated UI content,
    computes column-mean brightness across the rightmost 100 columns of
    the middle 60% of the panel height.  A scrollbar is detected when:
    -   the brightness profile range exceeds 10 (scrollbar gradient)
    -   the column std at the minimum is below 20 (uniform scrollbar gray)

Calibration accuracy (30 images):

-   Layout detection: 100%
-   Answer-panel scroll: 90% (3/4 answer-scroll, 1 weak signal missed)
-   No-scroll: 100% (0 false positives)
-   Q-panel scroll: known limitation (text noise masks scrollbar signal)

Final output:

stitched_question.png

This image represents the entire question context.

------------------------------------------------------------------------

### 6.2 AI Processing

Simulato uses a **Tiered AI Strategy** enhanced by **OCR Context Injection**.
Every question is sent directly to the cloud AI — there is no database pre-check
or image-hash cache layer in the processing path.

1.  **Primary Solver (Cloud AI):**
    -   **Vertex AI Gemini** (default primary): xAI's fast vision model with Structured Outputs.
    -   **Gemini 2.5 Flash** (fallback): Google's vision model, automatically engaged if Gemini fails parsing or transport.
    The primary solver is fed the stitched question image along with an **OCR Text Injection** (a complete raw transcript of all text extracted by Tesseract). This forces the LLM to ground its reasoning on the actual pixels, virtually eliminating hallucinated answers when watermarks degrade visual clarity.
    When the image is a multi-frame stitched composite, a dedicated `USER_PROMPT_STITCHED` message explicitly tells the AI to treat it as a single continuous question and deduplicate any repeated content.

2.  **Auxiliary Analyst Layer (OCR + Local Qwen):** Responsible for screen understanding and **never used to answer questions**:
    -   OCR Full-Screen Layout Pass on each processed question frame.
    -   Anchored preprocessing: top-bar template matching finds a stable ROI.
    -   Option Target Localization: determines the live pixel position of radio buttons.
    -   NEXT Button Localization: determines exact coordinates for the NEXT button.

**Coordinate Targeting (Split-Axis Blending):**
Option clicks use a robust Split-Axis Strategy to combine live OCR detection with pre-computed calibration:
-   **X-Axis (Horizontal):** Heavily uses calibration data, as radio button columns are perfectly stable across all questions.
-   **Y-Axis (Vertical):** Heavily uses live detection, as different question text lengths push the radio buttons up and down between questions.
If live Y-axis detection deviates too far from calibration (>120px), the system falls back entirely to pure calibration mapping.

The local analyst utilizes Ollama (e.g. `qwen2.5vl:7b-q4_K_M`) for
air-gapped or low-latency screen classification and is wrapped with a
short timeout plus cooldown so failures never stall the main pipeline.
For scroll verification, Ollama is the fallback when OCR confidence is low.

Processing steps:

1.  capture and stitch question image
2.  run OCR layout pass
3.  call Primary Solver (Vertex AI Gemini) with image + OCR context
4.  parse structured JSON response
5.  remap AI answer letter to live on-screen option content (handles shuffled options)

------------------------------------------------------------------------

# 8. QUESTION IDENTIFICATION ENGINE

Database-based question matching (SHA256, SimHash, embedding lookup) has been
**disabled** in the current pipeline.

Every question is treated as new and sent directly to the cloud AI.
The AI is always the source of truth for the answer.

The database schema and matching code are retained in the codebase but
are not called during normal question processing.

------------------------------------------------------------------------

# 9. ANSWER MATCHING

After the AI returns a structured JSON response, the system remaps the
returned answer letter to the **current live on-screen option content**.

Steps:

1.  AI returns answer letter (e.g. "A") and answer content text
2.  OCR reads current on-screen option texts from the answer panel
3.  System matches AI answer content against live option texts
4.  The live-matched letter is used for click dispatch

This guarantees correctness when options are shuffled between screens.

------------------------------------------------------------------------

# 10. HARDWARE INPUT TRANSACTION FLOW

All input actions must follow a verification workflow.

Sequence:

1.  derive click point (OCR first, then Local Qwen, then calibrated fallback)
2.  map to HID absolute coordinates
3.  send click command to Raspberry Pi
4.  capture dedicated verification screenshot
5.  detect visual highlight around the exact click target when available (normalized target verification)

If highlight detected:

action successful

If highlight missing:

retry same intended option once (with fresh option detection on the latest frame)

If retry fails:

trigger alert pause execution await operator decision

### 10.1 NEXT Click Verification

NEXT click success is verified using a multi-tier signal approach
comparing a pre-click reference frame against a post-click capture:

1.  **Tier 1 — Strong single signal:** question-panel diff > 4.5, OR
    full-frame diff > 5.5, OR pHash hamming distance ≥ 6.
2.  **Tier 2 — Combined weak signals:** question-panel diff > 3.5 AND
    pHash hamming ≥ 4 (catches borderline transitions missed by individual
    thresholds).
3.  If neither tier passes, a passive re-check is performed (1.5 s wait,
    new capture, same comparison) before concluding the click missed.
4.  Only after the re-check confirms no change does the system retry the
    NEXT click once.

These thresholds are calibrated to strongly avoid **false negatives**
(which cause destructive NEXT retries that skip questions) while accepting
the lower risk of false positives (which are caught by the pHash
same-screen guard on the next processing cycle).

------------------------------------------------------------------------

# 11. ALERT AND INTERVENTION SYSTEM

System alerts occur when:

-   AI answer conflicts with database
-   input verification fails
-   unexpected screen detected
-   answer option cannot be matched to on-screen options (NO_OPTION_MATCH)

Alert process:

1.  system triggers audible alarm
2.  remote phone displays alert
3.  operator options shown

Operator selects action before system continues.

------------------------------------------------------------------------

# 12. DATA STORAGE MODEL

Simulato stores AI responses as JSON files alongside screenshot artifacts
for each processed question. This enables debugging and replay.

Stored per-question artifacts (file-based):

-   screenshot (JPEG)
-   AI response JSON (question text, options, answer, model used)
-   event log entry (decision source, click letter, timing)

The **SQLite database** (`database/questions.db`) is present in the
codebase but question storage and lookup are **not performed** during
normal question processing. The database connection is initialized at
startup for future use.

Note: pHash is still computed for **NEXT-button navigation verification**
(detecting whether the screen actually changed after a NEXT click);
it is not used for question identity lookup.

------------------------------------------------------------------------

# 13. DATASET VERSIONING

AI response JSON files are written once per question capture and are
not modified. Each run produces its own artifact directory.

Dataset versioning via database records is not active in the current
pipeline.

------------------------------------------------------------------------

# 14. EXECUTION LOGGING

Every system event must be logged.

Log entries include:

-   timestamps
-   question number
-   AI provider and model used
-   AI answer (letter + content)
-   click letter dispatched
-   verification outcomes
-   operator interventions

Logs stored for replay and debugging.

------------------------------------------------------------------------

# 15. NETWORK ARCHITECTURE

Simulato operates primarily on local network.

Local communications:

-   capture phone → PC (HTTP + WebSocket)
-   remote phone → PC (HTTP + WebSocket)
-   PC → Raspberry Pi (TCP socket)
-   PC → Ollama (localhost HTTP)

Internet communication used for:

-   Vertex AI Gemini requests (api.x.ai)
-   Gemini Vision API requests (generativelanguage.googleapis.com)

All other operations occur locally.

Android network requirements:

-   The Android application must allow **cleartext HTTP traffic** for local
    network communication
-   Android Manifest must include: `android:usesCleartextTraffic="true"`
-   Alternatively, HTTPS may be used locally if configured

------------------------------------------------------------------------

# 16. REPLAY ENGINE

Simulato supports deterministic replay.

Replay uses stored artifacts:

-   screenshots
-   AI responses
-   decision logs

Replay execution reproduces:

-   identical decisions
-   identical input actions
-   identical results

Replay exists for debugging and experiment verification.

------------------------------------------------------------------------

# 17. SYSTEM EXECUTION FLOW

Complete run sequence:

1.  operator enters test name (if omitted by client, controller uses
    `default_test` deterministically)
2.  system enters RUNNING state
3.  question captured from Capture Phone
4.  screen validated (fail-safe)
5.  scroll detection run; additional frames captured if needed
6.  frames stitched into composite image
7.  OCR layout pass run on stitched image
8.  stitched image + OCR context sent **directly to cloud AI**
9.  AI response parsed (structured JSON)
10. answer letter remapped to live on-screen option content
11. click dispatched to Raspberry Pi
12. click verified via dedicated capture
13. NEXT clicked; navigation verified
14. loop to step 3 for next question

Loop continues until test completion.

STOP safety rule:

- If operator sends STOP during in-flight processing, controller stops scheduling next actions and does not continue fallback click loops.
- Remote START/CALIBRATE/PAUSE can recover deterministically from STOPPED via IDLE recovery.

------------------------------------------------------------------------

# 18. FAILURE HANDLING

Failures include:

-   AI response parse errors
-   AI API transport failures
-   input injection failure
-   unexpected screen layout
-   click verification failure

On failure:

1.  execution halts
2.  alert triggered
3.  operator intervention required

No silent recovery allowed.

------------------------------------------------------------------------

# 19. FINAL DECLARATION

This architecture defines the **official structural design of
Simulato**.

All implementation must follow this specification to ensure:

-   deterministic system behavior
-   reliable automation
-   reproducible research results
