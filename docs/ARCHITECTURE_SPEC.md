# SIMULATO SYSTEM ARCHITECTURE SPECIFICATION

## Project: Simulato

Version: 1.3.1\
Status: Authoritative Architecture Specification\
Last Updated: 2026-03-26

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
CLICK_NEXT\
SCROLL_LEFT\
SCROLL_RIGHT

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
-   validate local database for previous answers
-   stitch image segments
-   call Cloud AI (Grok) for primary question solving
-   call Local AI (Ollama/Qwen) for auxiliary screen analysis (scroll/answer verification)
-   process structured AI responses (via `response_format`)
-   perform database lookup
-   perform question matching
-   determine answer actions
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

------------------------------------------------------------------------

# 6. QUESTION CAPTURE PIPELINE

For each question:

1.  capture screenshot from the Capture Phone
2.  run the **local CV scroll detection pipeline** on the Main Control PC:
    -   `exam_layout.py` detects the split-pane layout (question/answer panels, divider)
    -   `scroll_detector.py` (v4) analyzes each panel independently for scrollbar presence
    -   detection uses structural UI-bounds isolation + column brightness profile analysis
3.  if scrolling is needed:
    -   command the Pi to scroll via HID
    -   request additional captures from the Capture Phone
    -   repeat scroll detection on each scroll frame until content is fully visible
4.  stitch all frames into a full question image

### 6.1 Scroll Detection Pipeline (v4)

Scroll detection is performed entirely via **local Computer Vision** on the
Main Control PC — no AI calls are used for scroll detection.

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

Simulato uses a **Tiered AI Strategy**:

1.  **Primary Solver (Cloud AI — selectable at runtime):**
    -   **Gemini 2.5 Flash** (default): Google's vision model via
        OpenAI-compatible endpoint.
    -   **Grok Vision**: xAI's vision model with Structured Outputs
        (JSON Schema).
    The active provider is selected by the operator from the Remote
    Control phone dropdown and can be switched at any time via the
    `SET_AI_PROVIDER` command.
2.  **Auxiliary Analyst Layer (OCR + Local Qwen):** Responsible for
screen understanding and **never used to answer questions**:
    -   OCR Full-Screen Layout Pass on each processed question frame
        (primary source for option/NEXT target localization).
    -   Scroll Verification (detecting clipped text), called for **every
        new screen and each scroll frame**.
    -   Answer Verification (detecting post-click highlights using
        dedicated verification captures).
    -   Option Target Localization (returning precise normalized click
        coordinates for A/B/C/D).
    -   NEXT Button Localization (returning precise normalized click
        coordinates, with calibrated-grid fallback).
    -   Screen Type Identification (login vs. question vs. error).

The local analyst utilizes Ollama (e.g. `qwen2.5vl:7b-q4_K_M`) for
air-gapped or low-latency screen classification and is wrapped with a
short timeout plus cooldown so failures never stall the main pipeline.

Processing steps:

1.  extract structured question data (from Primary Solver when needed)
2.  normalize text
3.  compute canonical representation
4.  perform database lookup (DB-first)
5.  if and only if **no matching question** is found in the database,
    call the Primary Solver (Grok/Gemini) for a new AI answer

------------------------------------------------------------------------

# 8. QUESTION IDENTIFICATION ENGINE

Matching occurs in multiple stages.

Stage 1 --- Canonical Hash Match
Stage 2 --- SimHash Similarity
Stage 3 --- Embedding Similarity
Stage 4 --- AI Query (fallback)

Matching is restricted to the **active test context**.

------------------------------------------------------------------------

# 9. ANSWER MATCHING

Answers must be selected using **option text**, not option position.

Steps:

1.  retrieve stored correct answer text
2.  compare with current option texts
3.  determine matching option index
4.  dispatch click command

This guarantees correctness when options are shuffled.

------------------------------------------------------------------------

# 10. HARDWARE INPUT TRANSACTION FLOW

All input actions must follow a verification workflow.

Sequence:

1.  derive click point (OCR first, then Local Qwen, then calibrated fallback)
2.  map to HID absolute coordinates
3.  send click command to Raspberry Pi
4.  capture screenshot
5.  detect visual highlight

If highlight detected:

action successful

If highlight missing:

retry click

If retry fails:

trigger alert pause execution await operator decision

------------------------------------------------------------------------

# 11. ALERT AND INTERVENTION SYSTEM

System alerts occur when:

-   AI answer conflicts with database
-   input verification fails
-   unexpected screen detected

Alert process:

1.  system triggers audible alarm
2.  remote phone displays alert
3.  operator options shown

Operator selects action before system continues.

------------------------------------------------------------------------

# 12. DATA STORAGE MODEL

Simulato stores full question snapshots.

Stored components:

-   screenshot
-   question text
-   options (A, B, C, D)
-   AI response (full JSON)
-   selected answer (text)
-   answer letter (A/B/C/D)
-   canonical hash (SHA256)
-   SimHash fingerprint (64-bit)
-   embedding vector (bge-small-en-v1.5)
-   image perceptual hash (pHash via DCT, 64-bit)
-   timestamps (ISO8601 UTC)
-   decision source (ai_new / database / database_image_hash / operator)

The `image_phash` field enables the **image-hash DB-first fast path**:
when a previously seen stitched image is captured again, the system
bypasses the AI call entirely and uses the cached answer directly.

This ensures experiment reproducibility.

------------------------------------------------------------------------

# 13. DATASET VERSIONING

Stored questions are immutable.

If a stored question changes:

-   new version created
-   previous version preserved

No silent modification allowed.

------------------------------------------------------------------------

# 14. EXECUTION LOGGING

Every system event must be logged.

Log entries include:

-   timestamps
-   question identifiers
-   AI calls
-   database hits
-   click commands
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

-   Grok Vision API requests (api.x.ai)
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
2.  system loads test context
3.  system enters RUNNING state
4.  question captured
5.  question processed
6.  answer determined
7.  click executed
8.  result verified
9.  next question triggered

Loop continues until test completion.

------------------------------------------------------------------------

# 18. FAILURE HANDLING

Failures include:

-   AI response errors
-   input injection failure
-   unexpected screen layout
-   database inconsistency

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
