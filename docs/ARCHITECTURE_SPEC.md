# SIMULATO SYSTEM ARCHITECTURE SPECIFICATION

## Project: Simulato

Version: 1.0\
Status: Authoritative Architecture Specification

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
`grid_map.json` file; without it, START commands are rejected.

### 5.1 Initial calibration

Steps:

1.  Operator positions capture phone
2.  Operator presses CALIBRATE on the Capture Phone
3.  Capture phone sends screen image
4.  PC detects exam layout
5.  PC constructs grid map
6.  Coordinates saved to configuration
7.  PC sends `CALIBRATION_RESULT` to both phones
8.  Capture phone shows a short (2–3 second) “Calibration successful”
    confirmation

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
2.  use the **Local Qwen analyst on every new screen** to:
    -   determine whether the screen is a valid question screen
    -   determine whether the question requires scrolling
3.  issue scroll command if necessary
4.  capture additional images
5.  stitch images into full question image

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
2.  **Auxiliary Analyst (Local Qwen):** Responsible for high-frequency
    screen understanding and **never used to answer questions**:
    -   Scroll Verification (detecting clipped text), called for **every
        new screen**.
    -   Answer Verification (detecting post-click highlights).
    -   Screen Type Identification (login vs. question vs. error).

The local analyst utilizes Ollama (e.g. `qwen2.5vl:7b`) for air-gapped
or low-latency screen classification.

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

1.  send click command to Raspberry Pi
2.  capture screenshot
3.  detect visual highlight

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
-   options
-   AI response
-   selected answer
-   canonical hash
-   embeddings
-   timestamps

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

-   capture phone → PC
-   remote phone → PC
-   PC → Raspberry Pi

Internet communication used for:

-   AI API requests (Ollama local / Grok cloud)
-   Mobile HTTP API

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

1.  operator enters test name
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
